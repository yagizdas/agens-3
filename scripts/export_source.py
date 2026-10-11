"""Export an explicit set of public files without credentials or Git history."""

import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = (
    "README.md",
    "NOTICE.md",
    "CONTRIBUTING.md",
    "pyproject.toml",
    ".gitignore",
    ".env.example",
)
PUBLIC_DIRS = ("src", "docs", "examples", "tests", "scripts", ".github", "archive")
SECRET_PATTERN = re.compile(
    rb"sk-(?:proj-)?[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}|"
    rb"gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
)


def source_files(root: Path = ROOT):
    candidates = [root / name for name in PUBLIC_FILES] + [root / "documents/README.md"]
    for name in PUBLIC_DIRS:
        candidates.extend((root / name).rglob("*"))
    for path in sorted(candidates):
        relative = path.relative_to(root)
        if not path.is_file() or path.is_symlink():
            continue
        if any(
            part in {"__pycache__", ".DS_Store", ".git", ".venv", ".pytest_cache", ".ruff_cache"}
            or part.endswith(".egg-info")
            for part in relative.parts
        ):
            continue
        if path.suffix in {".pyc", ".pyo"} or path.name == "secrets.toml":
            continue
        if path.name.startswith(".env") and path.name != ".env.example":
            continue
        if path.suffix in {".pem", ".key"}:
            continue
        yield path


def export_source(root: Path = ROOT) -> Path:
    files = list(source_files(root))
    # Validate every input before creating the archive. Matching values are never printed.
    for path in files:
        if SECRET_PATTERN.search(path.read_bytes()):
            raise ValueError(
                f"Possible credential found in {path.relative_to(root)}; export stopped."
            )
    destination = root / "dist/agens3-source.zip"
    destination.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, Path("agens3") / path.relative_to(root))
    return destination


if __name__ == "__main__":
    print(export_source())
