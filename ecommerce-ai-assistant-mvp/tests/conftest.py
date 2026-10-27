import pytest


@pytest.fixture(autouse=True)
def no_model_download(monkeypatch):
    """Tests use word + character vectors; embeddings are tested with a stand-in model."""
    monkeypatch.setenv("USE_EMBEDDINGS", "0")
