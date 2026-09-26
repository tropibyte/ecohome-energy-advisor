"""
Offline test fixtures.

ECOHOME_OFFLINE=1 is set before any project import, so the weather tool uses its
deterministic mock and the RAG index uses local hashing embeddings: the whole
suite runs without a network or an API key.  Each test session gets its own
temporary database and vector store; the real data/ folder is never touched.
"""
import os
import sys
from pathlib import Path
from typing import Any, List, Optional

os.environ["ECOHOME_OFFLINE"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
from langchain_core.language_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage, BaseMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402

import config  # noqa: E402
import tools  # noqa: E402
from models.energy import DatabaseManager  # noqa: E402
from sample_data import populate_database  # noqa: E402


@pytest.fixture(scope="session")
def populated_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "energy_test.db"
    db = DatabaseManager(str(path))
    populate_database(db, days=30, verbose=False)
    return db


@pytest.fixture(autouse=True)
def use_test_db(populated_db, monkeypatch):
    monkeypatch.setattr(tools, "db_manager", populated_db)
    tools._MODEL_CACHE.clear()
    yield


@pytest.fixture(scope="session")
def vector_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("vectorstore")


@pytest.fixture(autouse=True)
def use_test_vectorstore(vector_dir, monkeypatch):
    monkeypatch.setattr(config, "VECTORSTORE_DIR", vector_dir)
    yield


class ScriptedChatModel(BaseChatModel):
    """Returns pre-scripted AIMessages in order and records every prompt it received."""

    responses: List[Any] = []
    received: List[List[BaseMessage]] = []
    fail_times: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None,
                  run_manager=None, **kwargs) -> ChatResult:
        self.received.append(list(messages))
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("simulated gateway error")
        if not self.responses:
            msg = AIMessage(content="(script exhausted) final answer")
        else:
            item = self.responses.pop(0)
            msg = item if isinstance(item, AIMessage) else AIMessage(content=str(item))
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools, **kwargs):
        return self


def tool_call(name: str, args: dict, call_id: str = None) -> dict:
    return {"name": name, "args": args, "id": call_id or f"call_{name}", "type": "tool_call"}


@pytest.fixture
def scripted():
    def make(*responses, fail_times: int = 0):
        return ScriptedChatModel(responses=list(responses), received=[], fail_times=fail_times)
    return make
