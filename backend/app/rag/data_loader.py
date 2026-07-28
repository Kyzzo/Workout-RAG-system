from dotenv import load_dotenv
from llama_index.core.node_parser import SentenceSplitter
from llama_index.readers.file import PDFReader
from openai import OpenAI

load_dotenv()

client = OpenAI()

EMBED_MODEL = "text-embedding-3-large"
EMBED_DIM = 3072

# chunk_size: characters per chunk. chunk_overlap: characters repeated from
# the end of the previous chunk, so a chunk boundary doesn't cut off context.
splitter = SentenceSplitter(chunk_size=1000, chunk_overlap=200)


def load_and_chunk_pdf(path: str) -> list[str]:
    docs = PDFReader().load_data(file=path)
    texts = [d.text for d in docs if getattr(d, "text", None)]
    chunks = []
    for t in texts:
        chunks.extend(splitter.split_text(t))
    return chunks


def embed_texts(texts: list[str]) -> list[list[float]]:
    response = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [item.embedding for item in response.data]
