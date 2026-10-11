import os
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from initialize_knowledge_base import initialize_knowledge_base

def ingest_documents(folder_path):
    collection = initialize_knowledge_base()
    
    if isinstance(collection, str):
        print(f"Error initializing knowledge base: {collection}")
        return

    # Get existing sources to avoid re-ingesting
    existing_docs = collection.get()
    existing_sources = set()
    if existing_docs and 'metadatas' in existing_docs and existing_docs['metadatas']:
        for metadata in existing_docs['metadatas']:
            if metadata and 'source' in metadata:
                existing_sources.add(metadata['source'])
    
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200
    )

    if not os.path.exists(folder_path):
        print(f"Directory '{folder_path}' does not exist.")
        return

    for filename in os.listdir(folder_path):
        if filename.endswith(".pdf"):
            file_path = os.path.join(folder_path, filename)
            
            if filename in existing_sources:
                print(f"Skipping {filename} - already in knowledge base")
                continue
                
            print(f"Processing {filename}...")
            try:
                loader = PyPDFLoader(file_path)
                documents = loader.load()
                chunks = text_splitter.split_documents(documents)
                
                if not chunks:
                    print(f"No text found in {filename}")
                    continue

                ids = [f"{filename}_chunk_{i}" for i in range(len(chunks))]
                texts = [chunk.page_content for chunk in chunks]
                metadatas = [{"source": filename, "page": chunk.metadata.get("page", 0)} for chunk in chunks]
                
                collection.add(
                    documents=texts,
                    ids=ids,
                    metadatas=metadatas
                )
                print(f"Added {len(chunks)} chunks from {filename}")
            except Exception as e:
                print(f"Error processing {filename}: {e}")

if __name__ == "__main__":
    # Create documents directory if it doesn't exist
    if not os.path.exists("documents"):
        os.makedirs("documents")
        print("Created 'documents' directory. Please put your PDFs there.")
    else:
        ingest_documents("documents")
