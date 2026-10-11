"""Semantic search over the locally ingested documentation."""

from langchain_core.tools import tool


def create_search_knowledge_base_tool(collection):
    @tool("search_knowledge_base")
    def search_knowledge_base(keyword: str) -> list[str]:
        """Search ns-3 documentation for a keyword or natural-language query."""
        count = collection.count()
        if not count:
            return ["Knowledge base is empty. Run 'agens3 ingest', or read local ns-3 examples."]
        results = collection.query(query_texts=[keyword], n_results=min(3, count))
        documents = results.get("documents") or [[]]
        return documents[0] or []

    return search_knowledge_base
