import importlib.util
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/export_source.py"
spec = importlib.util.spec_from_file_location("export_source", SCRIPT)
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


def test_export_excludes_private_state(tmp_path):
    (tmp_path / "README.md").write_text("project")
    (tmp_path / ".env").write_text("private")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/module.py").write_text("print('hello')")
    (tmp_path / "src/__pycache__").mkdir()
    (tmp_path / "src/__pycache__/module.pyc").write_bytes(b"cache")
    (tmp_path / "src/secrets.toml").write_text("private")
    (tmp_path / "src/project.egg-info").mkdir()
    (tmp_path / "src/project.egg-info/PKG-INFO").write_text("generated metadata")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/config").write_text("old history")
    archive = export.export_source(tmp_path)
    with zipfile.ZipFile(archive) as zip_file:
        assert set(zip_file.namelist()) == {"agens3/README.md", "agens3/src/module.py"}


def test_export_stops_on_possible_credentials(tmp_path):
    # Deliberately assembled so the test source itself contains no secret-like value.
    (tmp_path / "README.md").write_text("sk-" + "x" * 30)
    with pytest.raises(ValueError, match="Possible credential"):
        export.export_source(tmp_path)
    assert not (tmp_path / "dist/agens3-source.zip").exists()
