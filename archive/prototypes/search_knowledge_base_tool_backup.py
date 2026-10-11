from langchain.tools import tool
from pydantic import BaseModel, Field

TOOL_NAME = "search_knowledge_base"
TOOL_DESCRIPTION = "Use this tool when you need to search the ns-3 knowledge database."


class KnowledgeBaseToolInput(BaseModel):
    keyword: str = Field(..., description="Keyword to search in the ns-3 database.")

def create_search_knowledge_base_tool(collection):
    """Factory function to create the search tool with injected collection and hierarchical support"""
    
    @tool("search_knowledge_base", description=TOOL_DESCRIPTION, args_schema=KnowledgeBaseToolInput)
    def search_knowledge_base(keyword: str, level: str = "api") -> list[str]:
        """
        Returns retrieval from ns-3 knowledge base based on the provided keyword and level.
        
        Args:
            keyword: Search query string
            level: 'summary', 'api', or 'code_example'
        
        Returns:
            List of relevant documentation strings
        """
        
        return collection.query(query_texts=[keyword], n_results=3)['documents'][0]
    
    return search_knowledge_base

if __name__ == "__main__":
    # Example usage
    from initialize_knowledge_base import initialize_knowledge_base
    collection = initialize_knowledge_base()
    search_tool = create_search_knowledge_base_tool(collection)
    
    # Test different levels
    print("=== SUMMARY LEVEL ===")
    result = search_tool.invoke({"keyword": "LTE handover", "level": "summary"})
    for item in result:
        print(item)
        print("\n---\n")
    
    print("\n=== API LEVEL ===")
    result = search_tool.invoke({"keyword": "LteHelper", "level": "api"})
    for item in result:
        print(item)
        print("\n---\n")
    
    print("\n=== CODE EXAMPLE LEVEL ===")
    result = search_tool.invoke({"keyword": "wifi transmission power", "level": "code_example"})
    for item in result:
        print(item)
        print("\n---\n")