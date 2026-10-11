from langchain.tools import tool
from pydantic import BaseModel, Field

TOOL_NAME = "search_knowledge_base"
TOOL_DESCRIPTION = """Use this tool to search the ns-3 hierarchical knowledge database.

The knowledge base has 3 levels:
- Level 1 (Summary): High-level guides and tutorials
- Level 2 (API): Specific class references and method signatures
- Level 3 (Code Examples): Verified code snippets from ns-3 examples

Specify which level to search for optimal results."""

class KnowledgeBaseToolInput(BaseModel):
    keyword: str = Field(..., description="Keyword to search in the ns-3 database.")
    level: str = Field(
        default="api", 
        description="Search level: 'summary', 'api', or 'code_example'. Default is 'api'."
    )

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
        # Adjust search parameters based on level
        n_results_map = {
            "summary": 2,      # High-level guides - fewer, broader results
            "api": 3,          # API docs - medium number of specific results
        }
        
        n_results = n_results_map.get(level, 3)
        
        # Enhance query based on level
        query_text = keyword
        if level == "summary":
            query_text = f"tutorial guide overview {keyword}"
        elif level == "api":
            query_text = f"class method API {keyword}"
        elif level == "code_example":
            query_text = f"example implementation {keyword}"
        
        try:
            results = collection.query(
                query_texts=[query_text], 
                n_results=n_results
            )
            
            docs = results.get('documents', [[]])[0]
            
            # Add metadata about the level
            formatted_results = [
                f"[Level: {level.upper()}] {doc}" 
                for doc in docs
            ]
            
            return formatted_results
            
        except Exception as e:
            return [f"Error searching knowledge base: {str(e)}"]
    
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