import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from dotenv import load_dotenv
import os

def initialize_knowledge_base():

    try:
        load_dotenv()
        os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
        client = chromadb.PersistentClient(path="./ns3_vector_db")

        collection = client.get_or_create_collection(
            name="ns-3-collection",
            embedding_function=OpenAIEmbeddingFunction(
                model_name="text-embedding-3-small"
            )
        )
        return collection
    
    except Exception as e:
        return str(e)

