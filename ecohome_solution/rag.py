"""
Retrieval pipeline for the EcoHome knowledge base.

Techniques used beyond plain similarity search:

1. **Contextual chunk headers** - each chunk is prefixed with its document
   title and section heading, so a chunk that says "run it after 9 PM" still
   carries "Pool and Spa Energy Management" into the embedding and BM25 index.
2. **Hybrid retrieval** - dense (OpenAI embeddings in Chroma) and sparse
   (BM25 keyword) rankings are fused with weighted Reciprocal Rank Fusion.  Dense
   search catches paraphrases ("cool the house before the price spike");
   BM25 catches exact terms ("NEM 3.0", "SEER2", "Level 2").
3. **Diversity re-ranking** - at most two chunks per source document in the
   final list, so one long document cannot crowd out every other viewpoint.
4. **Self-refreshing index** - a manifest of document hashes is stored with
   the vector store; when a document is added or edited the index is rebuilt.
   (The starter indexed a hard-coded list of two files, so documents added
   after running notebook 02 were silently never searched.)
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

import config

CHUNK_SIZE = 900
CHUNK_OVERLAP = 150
COLLECTION_NAME = "ecohome_energy_tips"
RRF_K = 60
# Weighted RRF: dense retrieval is the stronger ranker for natural-language questions, so BM25 acts as a
# tie-breaker and exact-term booster rather than an equal vote (equal weights let a weak keyword ranking push
# a dense rank-1 hit out of the top results).
DENSE_WEIGHT = 1.0
SPARSE_WEIGHT = 0.5
MAX_CHUNKS_PER_SOURCE = 2

_lock = threading.Lock()
_cache: Dict[str, object] = {}


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------
class HashingEmbeddings(Embeddings):
    """Offline stand-in: bag-of-words feature hashing (keyword-level semantics only).

    Used when ECOHOME_OFFLINE=1 so tests and demos run without an API key.
    """

    def __init__(self, dim: int = 512):
        self.dim = dim

    def _embed(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        for tok in tokenize(text):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            vec[h % self.dim] += 1.0 if (h >> 20) & 1 else -1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._embed(text)


def get_embeddings() -> Embeddings:
    if config.OFFLINE or not config.get_api_key():
        return HashingEmbeddings()
    from langchain_openai import OpenAIEmbeddings
    return OpenAIEmbeddings(model=config.EMBEDDING_MODEL, **config.openai_client_kwargs())


def embedding_id() -> str:
    return "hashing-512" if isinstance(get_embeddings(), HashingEmbeddings) else config.EMBEDDING_MODEL


# ---------------------------------------------------------------------------
# Loading and splitting
# ---------------------------------------------------------------------------
_STOP = set("""a an the and or of to in on for with at by from is are be it this that as
your you can if when than then into during about more most less up out""".split())


def _stem(tok: str) -> str:
    """Very light plural stemming so 'events' matches 'event' and 'pumps' matches 'pump'."""
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss") and not tok[-2].isdigit():
        return tok[:-1]
    return tok


def tokenize(text: str) -> List[str]:
    """Lower-case word tokens; hyphens split ('critical-peak' -> critical, peak), decimals kept ('3.0')."""
    return [_stem(t) for t in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower()) if t not in _STOP]


def document_paths(documents_dir: Path = None) -> List[Path]:
    documents_dir = Path(documents_dir or config.DOCUMENTS_DIR)
    return sorted(p for p in documents_dir.iterdir() if p.suffix.lower() in (".txt", ".md") and p.is_file())


def documents_fingerprint(paths: List[Path]) -> Dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()[:16] for p in paths}


def _title_for(path: Path, text: str) -> str:
    first = text.strip().splitlines()[0].strip() if text.strip() else path.stem
    first = first.lstrip("#").strip()
    if len(first) > 80 or first.endswith("."):  # starter docs open with a sentence, not a title
        return path.stem.replace("tip_", "").replace("_", " ").title()
    return first


def load_documents(documents_dir: Path = None) -> List[Document]:
    """Load every .txt/.md file in data/documents with source and title metadata."""
    docs = []
    for path in document_paths(documents_dir):
        text = path.read_text(encoding="utf-8")
        docs.append(Document(page_content=text, metadata={"source": path.name, "title": _title_for(path, text)}))
    return docs


def split_documents(documents: List[Document]) -> List[Document]:
    """Split on section boundaries first, then add a contextual header to every chunk."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP, length_function=len,
        separators=["\n## ", "\n\n", "\n", ". ", " ", ""],
    )
    chunks: List[Document] = []
    for doc in documents:
        section = ""
        for i, piece in enumerate(splitter.split_documents([doc])):
            heading = re.findall(r"^#+\s*(.+)$", piece.page_content, flags=re.M)
            if heading:
                section = heading[0].strip()
            header = f"[{doc.metadata['title']}" + (f" > {section}" if section else "") + "]"
            piece.page_content = f"{header}\n{piece.page_content.strip()}"
            piece.metadata.update({"chunk_index": i, "section": section})
            chunks.append(piece)
    return chunks


# ---------------------------------------------------------------------------
# Vector store lifecycle
# ---------------------------------------------------------------------------
def _manifest_path(persist_directory: Path) -> Path:
    return Path(persist_directory) / "ecohome_manifest.json"


def vectorstore_is_current(persist_directory: Path = None, documents_dir: Path = None) -> bool:
    persist_directory = Path(persist_directory or config.VECTORSTORE_DIR)
    mpath = _manifest_path(persist_directory)
    if not (persist_directory / "chroma.sqlite3").exists() or not mpath.exists():
        return False
    manifest = json.loads(mpath.read_text())
    return (manifest.get("documents") == documents_fingerprint(document_paths(documents_dir))
            and manifest.get("embedding") == embedding_id()
            and manifest.get("chunk_size") == CHUNK_SIZE)


def build_vectorstore(persist_directory: Path = None, documents_dir: Path = None):
    """(Re)build the Chroma collection from every document on disk."""
    documents = load_documents(documents_dir)
    splits = split_documents(documents)
    store = create_vectorstore(splits, persist_directory, documents_dir)
    return store, len(documents), len(splits)


def create_vectorstore(splits: List[Document], persist_directory: Path = None, documents_dir: Path = None):
    """Embed the chunks into a fresh Chroma collection and write the manifest of document hashes."""
    from langchain_chroma import Chroma
    persist_directory = Path(persist_directory or config.VECTORSTORE_DIR)
    persist_directory.mkdir(parents=True, exist_ok=True)
    embeddings = get_embeddings()
    store = Chroma(collection_name=COLLECTION_NAME, embedding_function=embeddings,
                   persist_directory=str(persist_directory))
    store.delete_collection()  # drop stale chunks from an older document set
    store = Chroma.from_documents(documents=splits, embedding=embeddings, collection_name=COLLECTION_NAME,
                                  persist_directory=str(persist_directory),
                                  collection_metadata={"hnsw:space": "cosine"})
    _manifest_path(persist_directory).write_text(json.dumps({
        "documents": documents_fingerprint(document_paths(documents_dir)),
        "embedding": embedding_id(), "chunk_size": CHUNK_SIZE, "chunk_overlap": CHUNK_OVERLAP,
        "chunks": len(splits),
    }, indent=2))
    _cache.clear()
    _cache[str(persist_directory)] = store
    return store


def load_vectorstore(persist_directory: Path = None):
    """Reopen the persisted collection (cached per directory within the process)."""
    from langchain_chroma import Chroma
    persist_directory = Path(persist_directory or config.VECTORSTORE_DIR)
    if str(persist_directory) in _cache:
        return _cache[str(persist_directory)]
    _cache[str(persist_directory)] = store = Chroma(collection_name=COLLECTION_NAME, embedding_function=get_embeddings(),
                  persist_directory=str(persist_directory),
                  collection_metadata={"hnsw:space": "cosine"})
    return store


def get_vectorstore(persist_directory: Path = None, documents_dir: Path = None) -> Tuple[object, str]:
    """Return (store, how) where how is 'loaded', 'built' or 'rebuilt'."""
    persist_directory = Path(persist_directory or config.VECTORSTORE_DIR)
    key = str(persist_directory)
    with _lock:
        if key in _cache and vectorstore_is_current(persist_directory, documents_dir):
            return _cache[key], "cached"
        existed = (persist_directory / "chroma.sqlite3").exists()
        if vectorstore_is_current(persist_directory, documents_dir):
            store, how = load_vectorstore(persist_directory), "loaded"
        else:
            store, _, _ = build_vectorstore(persist_directory, documents_dir)
            how = "rebuilt" if existed else "built"
        _cache[key] = store
        _cache.pop(key + ":bm25", None)
        return store, how


# ---------------------------------------------------------------------------
# Hybrid search
# ---------------------------------------------------------------------------
def _bm25_index(store, key: str):
    from rank_bm25 import BM25Okapi
    cached = _cache.get(key + ":bm25")
    if cached is not None:
        return cached
    got = store.get(include=["documents", "metadatas"])
    docs = [Document(page_content=t, metadata=m or {}) for t, m in zip(got["documents"], got["metadatas"])]
    index = (BM25Okapi([tokenize(d.page_content) for d in docs]), docs)
    _cache[key + ":bm25"] = index
    return index


def hybrid_search(query: str, k: int = 5, persist_directory: Path = None,
                  documents_dir: Path = None, store=None) -> Dict[str, object]:
    persist_directory = Path(persist_directory or config.VECTORSTORE_DIR)
    if store is None:
        store, how = get_vectorstore(persist_directory, documents_dir)
    else:
        how = "supplied by caller"
    fetch_k = max(12, 3 * k)

    # Dense ranking.
    dense = store.similarity_search_with_relevance_scores(query, k=fetch_k)
    # Sparse ranking.
    bm25, all_docs = _bm25_index(store, str(persist_directory))
    scores = bm25.get_scores(tokenize(query))
    sparse_order = sorted(range(len(all_docs)), key=lambda i: scores[i], reverse=True)[:fetch_k]

    def key_of(doc: Document) -> str:
        return f"{doc.metadata.get('source')}#{doc.metadata.get('chunk_index')}"

    fused: Dict[str, Dict] = {}
    for rank, (doc, sim) in enumerate(dense):
        entry = fused.setdefault(key_of(doc), {"doc": doc, "rrf": 0.0, "vector_score": None, "bm25_score": None})
        entry["rrf"] += DENSE_WEIGHT / (RRF_K + rank + 1)
        entry["vector_score"] = round(float(sim), 4)
    max_bm25 = max(scores) if len(scores) else 0
    for rank, i in enumerate(sparse_order):
        if scores[i] <= 0:
            break
        doc = all_docs[i]
        entry = fused.setdefault(key_of(doc), {"doc": doc, "rrf": 0.0, "vector_score": None, "bm25_score": None})
        entry["rrf"] += SPARSE_WEIGHT / (RRF_K + rank + 1)
        entry["bm25_score"] = round(float(scores[i] / max_bm25), 4) if max_bm25 else 0.0

    ranked = sorted(fused.values(), key=lambda e: e["rrf"], reverse=True)
    per_source: Dict[str, int] = {}
    selected = []
    for e in ranked:
        src = e["doc"].metadata.get("source", "unknown")
        if per_source.get(src, 0) >= MAX_CHUNKS_PER_SOURCE:
            continue
        per_source[src] = per_source.get(src, 0) + 1
        selected.append(e)
        if len(selected) == k:
            break
    top = selected[0]["rrf"] if selected else 1.0
    return {"results": selected, "top_rrf": top, "index_status": how,
            "candidates": {"dense": len(dense), "sparse": len([i for i in sparse_order if scores[i] > 0])}}
