import json
from unittest.mock import Mock

import pytest

from agens3.cli import main
from agens3.config import Settings


def test_missing_key_has_actionable_error(capsys):
    assert main(["run", "--prompt", "network scenario"]) == 1
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_doctor_is_offline_and_does_not_print_key(settings, monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-value")
    monkeypatch.setenv("NS3_DIR", str(settings.ns3_dir))
    assert main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "configured" in output and "test-secret-value" not in output


def test_environment_overrides_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("OPENAI_MODEL=from-file\nNS3_DIR=./custom-ns3\n")
    monkeypatch.setenv("OPENAI_MODEL", "from-environment")
    settings = Settings.from_env()
    assert settings.openai_model == "from-environment"
    assert settings.ns3_dir == tmp_path / "custom-ns3"


@pytest.mark.parametrize("value", ["0", "-1", "not-an-integer"])
def test_invalid_timeout_is_rejected(monkeypatch, value):
    monkeypatch.setenv("NS3_TIMEOUT", value)
    with pytest.raises(ValueError):
        Settings.from_env()


def test_cli_writes_json_and_code(settings, monkeypatch):
    import agens3.workflow

    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-value")
    monkeypatch.setenv("NS3_DIR", str(settings.ns3_dir))
    monkeypatch.setenv("OUTPUT_DIR", str(settings.output_dir))
    graph = Mock()
    graph.invoke.return_value = {
        "question": "scenario",
        "final_answer": "completed",
        "coder_output": "int main() {}",
        "coder_language": "cpp",
        "visited_nodes": ["manager", "final"],
    }
    monkeypatch.setattr(agens3.workflow, "create_workflow", Mock(return_value=graph))
    assert main(["run", "--prompt", "scenario"]) == 0
    logs = list(settings.output_dir.glob("*.json"))
    assert len(logs) == 1
    assert json.loads(logs[0].read_text())["final_answer"] == "completed"
    assert logs[0].with_suffix(".cc").read_text() == "int main() {}"
