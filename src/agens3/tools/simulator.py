"""Compile and run generated simulations using a local ns-3 installation."""

import os
import subprocess
import sys
import uuid

from langchain_core.tools import tool

from ..config import Settings


def run_simulation(code: str, language: str, settings: Settings | None = None) -> str:
    settings = settings or Settings.from_env()
    if language not in {"cpp", "python"}:
        return "Invalid language. Use 'cpp' or 'python'."
    settings.require_ns3()
    if language == "cpp":
        target = f"agens3_{uuid.uuid4().hex}"
        source = settings.ns3_dir / "scratch" / f"{target}.cc"
        source.write_text(code, encoding="utf-8")
        command = [str(settings.ns3_dir / "ns3"), "run", target]
    else:
        command = [sys.executable, "-c", code]
    try:
        result = subprocess.run(
            command,
            cwd=settings.ns3_dir,
            capture_output=True,
            text=True,
            timeout=settings.simulation_timeout,
            env={**os.environ, "NS_LOG": "ns3Agent=info"},
        )
    except subprocess.TimeoutExpired as exc:
        return f"Simulation timed out after {settings.simulation_timeout}s.\n{exc}"
    return f"Exit code: {result.returncode}\n{result.stdout}{result.stderr}"


@tool("ns3_tool")
def Ns3Tool(code: str, language: str) -> str:
    """Compile and run ns-3 C++ or Python code; return exit status and raw output."""
    return run_simulation(code, language)


def create_simulator_tool(settings: Settings):
    @tool("ns3_tool")
    def run_configured_simulation(code: str, language: str) -> str:
        """Compile and run ns-3 C++ or Python code; return exit status and raw output."""
        return run_simulation(code, language, settings)

    return run_configured_simulation
