import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agens3.tools.examples import list_examples, read_example
from agens3.tools.knowledge_search import create_search_knowledge_base_tool
from agens3.tools.simulator import run_simulation


def test_cpp_execution_preserves_errors_and_unique_sources(settings, monkeypatch):
    run = Mock(
        return_value=SimpleNamespace(returncode=1, stdout="build log\n", stderr="error: API\n")
    )
    monkeypatch.setattr(subprocess, "run", run)
    output = run_simulation("int main() {}", "cpp", settings)
    first_target = run.call_args.args[0][-1]
    run_simulation("int main() { return 0; }", "cpp", settings)
    assert run.call_args.args[0][-1] != first_target
    assert (settings.ns3_dir / "scratch" / f"{first_target}.cc").read_text() == "int main() {}"
    assert "Exit code: 1" in output and "error: API" in output
    assert run.call_args.kwargs["cwd"] == settings.ns3_dir
    assert run.call_args.kwargs["timeout"] == 300


def test_python_uses_current_interpreter(settings, monkeypatch):
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="3\n", stderr=""))
    monkeypatch.setattr(subprocess, "run", run)
    assert "3\n" in run_simulation("print(3)", "python", settings)
    assert run.call_args.args[0] == [sys.executable, "-c", "print(3)"]


def test_timeout_returns_feedback(settings, monkeypatch):
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=subprocess.TimeoutExpired("ns3", 300)))
    assert "timed out" in run_simulation("int main() {}", "cpp", settings)


def test_examples_use_configured_source_tree(settings):
    directory = settings.ns3_dir / "src/wifi/examples"
    directory.mkdir(parents=True)
    (directory / "wifi-demo.cc").write_text("// source code")
    assert "wifi-demo" in list_examples("wifi", settings)
    assert "// source code" in read_example("wifi-demo", settings)
    assert "directory path" in read_example("../../outside", settings)


def test_empty_collection_does_not_request_embeddings():
    collection = Mock()
    collection.count.return_value = 0
    output = create_search_knowledge_base_tool(collection).invoke("wifi")
    assert "empty" in output[0]
    collection.query.assert_not_called()


def test_small_collection_limits_results():
    collection = Mock()
    collection.count.return_value = 1
    collection.query.return_value = {"documents": [["reference"]]}
    assert create_search_knowledge_base_tool(collection).invoke("wifi") == ["reference"]
    collection.query.assert_called_once_with(query_texts=["wifi"], n_results=1)


def test_ingest_rejects_empty_directory_before_api_calls(tmp_path):
    from agens3.knowledge_base import ingest_documents

    with pytest.raises(ValueError, match="No PDF"):
        ingest_documents(tmp_path)
