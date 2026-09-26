"""Offline tests for the RAG pipeline (hashing embeddings + BM25, temporary vector store)."""
import shutil

import config
import rag
import tools


def test_all_documents_are_indexed_and_cited():
    paths = rag.document_paths()
    assert len(paths) >= 7  # 2 starter + at least 5 added
    r = tools.search_energy_tips.invoke({"query": "pre-cool the house before the peak price", "max_results": 5})
    assert "error" not in r, r
    assert r["total_results"] == 5
    sources = [t["source"] for t in r["tips"]]
    assert "tip_hvac_optimization.txt" in sources
    assert r["tips"][0]["relevance_score"] == "high"
    assert all(t["content"].startswith("[") for t in r["tips"])  # contextual chunk header


def test_keyword_search_finds_exact_terms():
    # Two documents legitimately discuss NEM 3.0 exports; the solar one must be among the top results
    # and every hit must carry a keyword score (BM25 found the exact term).
    r = tools.search_energy_tips.invoke({"query": "NEM 3.0 export credit", "max_results": 3})
    assert "tip_renewable_solar_integration.txt" in [t["source"] for t in r["tips"]]
    assert all(t["keyword_score"] for t in r["tips"])
    hyphen = tools.search_energy_tips.invoke({"query": "critical peak event", "max_results": 3})
    assert "tip_time_of_use_rates.txt" in [t["source"] for t in hyphen["tips"]]  # matches 'Critical-peak events'


def test_diversity_limits_chunks_per_source():
    r = tools.search_energy_tips.invoke({"query": "battery", "max_results": 8})
    counts = {}
    for t in r["tips"]:
        counts[t["source"]] = counts.get(t["source"], 0) + 1
    assert max(counts.values()) <= rag.MAX_CHUNKS_PER_SOURCE


def test_index_rebuilds_when_a_document_is_added(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    shutil.copytree(config.DOCUMENTS_DIR, docs)
    store_dir = tmp_path / "store"
    _, how = rag.get_vectorstore(store_dir, docs)
    assert how == "built"
    _, how = rag.get_vectorstore(store_dir, docs)
    assert how == "cached"
    (docs / "tip_new_topic.txt").write_text("# Heat Pump Dryers\n\nHeat pump dryers recycle warm air.", encoding="utf-8")
    assert not rag.vectorstore_is_current(store_dir, docs)
    _, how = rag.get_vectorstore(store_dir, docs)
    assert how == "rebuilt"
    hits = rag.hybrid_search("heat pump dryer recycle", k=2, persist_directory=store_dir, documents_dir=docs)
    assert hits["results"][0]["doc"].metadata["source"] == "tip_new_topic.txt"
