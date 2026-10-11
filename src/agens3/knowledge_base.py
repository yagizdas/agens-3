"""Persistent PDF retrieval backed by Chroma and OpenAI embeddings."""

from pathlib import Path

from .config import Settings


def initialize_knowledge_base(settings: Settings | None = None):
    import chromadb
    from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

    settings = settings or Settings.from_env()
    settings.require_api_key()
    client = chromadb.PersistentClient(path=str(settings.vector_db_dir))
    return client.get_or_create_collection(
        name="ns-3-collection",
        embedding_function=OpenAIEmbeddingFunction(
            api_key=settings.openai_api_key, model_name=settings.embedding_model
        ),
    )


def ingest_documents(folder: Path, settings: Settings | None = None) -> int:
    """Add previously unseen PDFs; return the number of new chunks."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from pypdf import PdfReader

    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError(f"Document directory does not exist: {folder}")
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        raise ValueError(f"No PDF files found in {folder}.")
    collection = initialize_knowledge_base(settings)
    existing = collection.get().get("metadatas") or []
    sources = {item["source"] for item in existing if item and "source" in item}
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    added = 0
    for pdf in pdfs:
        if pdf.name in sources:
            print(f"Skipping {pdf.name}: already indexed.")
            continue
        texts, ids, metadata = [], [], []
        for page_number, page in enumerate(PdfReader(pdf).pages):
            for index, chunk in enumerate(splitter.split_text(page.extract_text() or "")):
                texts.append(chunk)
                ids.append(f"{pdf.name}:page{page_number}:chunk{index}")
                metadata.append({"source": pdf.name, "page": page_number})
        for start in range(0, len(texts), 100):
            collection.add(
                documents=texts[start : start + 100],
                ids=ids[start : start + 100],
                metadatas=metadata[start : start + 100],
            )
        added += len(texts)
        print(f"Indexed {pdf.name}: {len(texts)} chunks.")
    return added
