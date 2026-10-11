"""Command-line entry point with an offline setup check."""

import argparse
import datetime
import json
import sys
import uuid
from pathlib import Path

from .config import Settings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="agens-3: natural language to ns-3 simulations")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check configuration without making API calls")
    ingest = commands.add_parser("ingest", help="Index ns-3 PDFs (uses OpenAI embeddings)")
    ingest.add_argument("folder", nargs="?", type=Path)
    run = commands.add_parser("run", help="Generate, execute, and evaluate a simulation")
    query = run.add_mutually_exclusive_group(required=True)
    query.add_argument("--prompt", help="A fully specified simulation scenario")
    query.add_argument("--prompt-file", type=Path, help="Read a scenario from a text file")
    run.add_argument("--recursion-limit", type=int, default=300)
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
        if args.command == "doctor":
            key_ready = bool(settings.openai_api_key)
            ns3_ready = (settings.ns3_dir / "ns3").is_file() and (
                settings.ns3_dir / "scratch"
            ).is_dir()
            print(f"OpenAI key: {'configured' if key_ready else 'missing'}")
            print(f"Model: {settings.openai_model}")
            print(f"ns-3 tree: {'found' if ns3_ready else 'missing'} ({settings.ns3_dir})")
            print(f"Vector database: {settings.vector_db_dir}")
            print(f"Outputs: {settings.output_dir}")
            return 0 if key_ready and ns3_ready else 1
        settings.require_api_key()
        if args.command == "ingest":
            from .knowledge_base import ingest_documents

            count = ingest_documents(args.folder or settings.documents_dir, settings)
            print(f"Added {count} new chunks.")
            return 0
        settings.require_ns3()
        question = (
            args.prompt if args.prompt is not None else args.prompt_file.read_text(encoding="utf-8")
        )
        if not question.strip():
            raise ValueError("The simulation prompt cannot be empty.")
        if args.recursion_limit <= 0:
            raise ValueError("The recursion limit must be positive.")
        from .workflow import create_workflow

        result = create_workflow(settings).invoke(
            {
                "question": question,
                "thoughts": [],
                "actions": [],
                "observations": [],
                "iteration": 0,
                "visited_nodes": [],
            },
            config={"recursion_limit": args.recursion_limit},
        )
        settings.output_dir.mkdir(parents=True, exist_ok=True)
        output = settings.output_dir / f"workflow_{uuid.uuid4().hex}.json"
        log = {"timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(), **result}
        output.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
        if result.get("coder_output"):
            suffix = ".py" if result.get("coder_language") == "python" else ".cc"
            output.with_suffix(suffix).write_text(result["coder_output"], encoding="utf-8")
        print(
            f"\n{result.get('final_answer', 'No final answer returned.')}\n\nWorkflow saved to {output}"
        )
        return 0
    except Exception as exc:
        print(f"agens3: {exc}", file=sys.stderr)
        return 1
