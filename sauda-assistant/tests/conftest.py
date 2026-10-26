import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sauda import ingest  # noqa: E402
from sauda.db import Repo  # noqa: E402

CSV = str(ROOT / "data" / "sample_pk_grocery.csv")


@pytest.fixture
def repo(tmp_path):
    return Repo(tmp_path / "test.db")


@pytest.fixture
def scope(repo):
    s = repo.add_store("demo-mart", "Demo Mart", "demo-khi", "Karachi", api_key="demo-store-key")
    ingest.sync(repo, s, CSV)
    return s


# ------------------------------------------------------------ fake Claude

def text(t):
    return NS(type="text", text=t)


def tool(name, args, id_):
    return NS(type="tool_use", name=name, input=args, id=id_)


def resp(*blocks, stop="end_turn"):
    return NS(content=list(blocks), stop_reason=stop, usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0))


class FakeClient:
    """Replays scripted responses; records every request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.calls.append({**kw, "messages": list(kw["messages"])})
        if not self.responses:
            raise AssertionError("FakeClient ran out of scripted responses")
        step = self.responses.pop(0)
        return step(kw) if callable(step) else step
