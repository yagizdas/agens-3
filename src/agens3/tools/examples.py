"""Read source examples from the configured ns-3 checkout."""

import re
from pathlib import Path

from langchain_core.tools import tool

from ..config import Settings


def _valid_name(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]+", value))


def _example_paths(base: Path, name: str):
    patterns = (f"src/*/examples/{name}.cc", f"examples/**/{name}.cc", f"scratch/{name}.cc")
    for pattern in patterns:
        for path in sorted(base.glob(pattern)):
            if path.resolve().is_relative_to(base.resolve()):
                yield path


@tool
def read_ns3_example(example_name: str) -> str:
    """Read an ns-3 C++ example by name without .cc, such as tcp-bulk-send."""
    return read_example(example_name, Settings.from_env())


def read_example(example_name: str, settings: Settings) -> str:
    if not _valid_name(example_name):
        return "Use an example name without an extension or directory path."
    settings.require_ns3()
    for path in _example_paths(settings.ns3_dir, example_name):
        content = path.read_text(encoding="utf-8")
        return f"Found: {path.relative_to(settings.ns3_dir)}\n\n{content}"
    return f"Example '{example_name}' not found. Use list_ns3_examples to discover examples."


@tool
def list_ns3_examples(module: str = "lte") -> str:
    """List local ns-3 examples in a module such as lte, wifi, or applications."""
    return list_examples(module, Settings.from_env())


def list_examples(module: str, settings: Settings) -> str:
    if not _valid_name(module):
        return "Use a module name without a directory path."
    settings.require_ns3()
    paths = list(settings.ns3_dir.glob(f"src/{module}/examples/*.cc")) + list(
        settings.ns3_dir.glob(f"examples/{module}/**/*.cc")
    )
    names = sorted({path.stem for path in paths})
    return "\n".join(names) if names else f"No examples found for module '{module}'."


def create_example_tools(settings: Settings):
    @tool("read_ns3_example")
    def read_configured_example(example_name: str) -> str:
        """Read an ns-3 C++ example by name without its .cc extension."""
        return read_example(example_name, settings)

    @tool("list_ns3_examples")
    def list_configured_examples(module: str = "lte") -> str:
        """List ns-3 C++ examples for a module such as wifi, lte, or applications."""
        return list_examples(module, settings)

    return read_configured_example, list_configured_examples
