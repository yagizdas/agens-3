import pytest

from agens3.config import Settings


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Never read the user's real .env or make real model requests during tests."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("NS3_TIMEOUT", raising=False)


@pytest.fixture
def settings(tmp_path):
    ns3 = tmp_path / "ns3"
    ns3.mkdir()
    (ns3 / "ns3").write_text("placeholder launcher")
    (ns3 / "scratch").mkdir()
    return Settings(ns3_dir=ns3, output_dir=tmp_path / "outputs")
