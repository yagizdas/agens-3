"""Environment configuration shared by the CLI and tools."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    embedding_model: str = "text-embedding-3-small"
    ns3_dir: Path = Path("ns-3.46.1")
    vector_db_dir: Path = Path("ns3_vector_db")
    documents_dir: Path = Path("documents")
    output_dir: Path = Path("outputs")
    simulation_timeout: int = 300

    @classmethod
    def from_env(cls):
        load_dotenv(Path.cwd() / ".env")
        timeout = int(os.getenv("NS3_TIMEOUT", "300"))
        if timeout <= 0:
            raise ValueError("NS3_TIMEOUT must be a positive number of seconds.")
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            ns3_dir=Path(os.getenv("NS3_DIR", "ns-3.46.1")).expanduser().resolve(),
            vector_db_dir=Path(os.getenv("VECTOR_DB_DIR", "ns3_vector_db")).expanduser().resolve(),
            documents_dir=Path(os.getenv("DOCUMENTS_DIR", "documents")).expanduser().resolve(),
            output_dir=Path(os.getenv("OUTPUT_DIR", "outputs")).expanduser().resolve(),
            simulation_timeout=timeout,
        )

    def require_api_key(self):
        if not self.openai_api_key:
            raise ValueError("Set OPENAI_API_KEY in your environment or .env file.")

    def require_ns3(self):
        if not (self.ns3_dir / "ns3").is_file() or not (self.ns3_dir / "scratch").is_dir():
            raise ValueError("NS3_DIR must point to an ns-3 tree containing ns3 and scratch/.")
