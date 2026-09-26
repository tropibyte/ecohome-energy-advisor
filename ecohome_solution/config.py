"""
Central configuration for the EcoHome Energy Advisor.

Every path is anchored to this file's directory, so notebooks, tests and
scripts behave the same no matter which working directory they start from.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
DOCUMENTS_DIR = DATA_DIR / "documents"
VECTORSTORE_DIR = DATA_DIR / "vectorstore"
DB_PATH = DATA_DIR / "energy_data.db"
REPORTS_DIR = PROJECT_ROOT / "reports"

# .env may sit in the solution folder or one level up (repo root).
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT.parent / ".env")

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://openai.vocareum.com/v1")
CHAT_MODEL = os.getenv("ECOHOME_CHAT_MODEL", "gpt-4.1-mini")
JUDGE_MODEL = os.getenv("ECOHOME_JUDGE_MODEL", "gpt-4o")
EMBEDDING_MODEL = os.getenv("ECOHOME_EMBEDDING_MODEL", "text-embedding-3-small")

# When set to "1" every external call (Open-Meteo) is skipped and the
# deterministic mock is used instead.  The offline test-suite sets this.
OFFLINE = os.getenv("ECOHOME_OFFLINE", "0") == "1"


def get_api_key() -> str | None:
    """Vocareum key first (course environment), then a plain OpenAI key."""
    return os.getenv("VOCAREUM_API_KEY") or os.getenv("OPENAI_API_KEY")


def openai_client_kwargs() -> dict:
    """Keyword arguments shared by ChatOpenAI and OpenAIEmbeddings."""
    kwargs = {"api_key": get_api_key()}
    if OPENAI_BASE_URL:
        kwargs["base_url"] = OPENAI_BASE_URL
    return kwargs
