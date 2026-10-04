import re
import unicodedata

from dotenv import load_dotenv
from llama_index.core.node_parser import SentenceSplitter
from openai import OpenAI
from pypdf import PdfReader

load_dotenv()

client = OpenAI()

EMBED_MODEL = "text-embedding-3-large"
EMBED_DIM = 3072

# chunk_size: characters per chunk. chunk_overlap: characters repeated from
# the end of the previous chunk, so a chunk boundary doesn't cut off context.
splitter = SentenceSplitter(chunk_size=1000, chunk_overlap=200)


_WORD = re.compile(r"[A-Za-z]+")


def _merged_word_ratio(text: str) -> float:
    # Share of 'words' over 20 letters - real words almost never are, so a
    # high share means the extractor dropped the spaces ("Resistancetraining
    # (RT)outcomesdependonmanyfactors...").
    words = _WORD.findall(text)
    return sum(len(w) > 20 for w in words) / max(len(words), 1)


def _page_text(page) -> str:
    """Plain extraction, falling back to layout mode on pages where it lost
    the spaces between words. Layout mode isn't the default: it keeps the
    page's visual layout, which interleaves the lines of two-column journal
    pages. Ligatures ('ﬁ') are normalized to plain letters."""
    text = page.extract_text() or ""
    # 1%: a clean page scores 0 (every page of every other ingested paper
    # does); table pages with lost spaces score as low as ~1.3%.
    if _merged_word_ratio(text) > 0.01:
        layout = page.extract_text(extraction_mode="layout") or ""
        if _merged_word_ratio(layout) < _merged_word_ratio(text):
            text = "\n".join(" ".join(line.split()) for line in layout.splitlines() if line.strip())
    return unicodedata.normalize("NFKC", text)


def load_and_chunk_pdf(path: str) -> list[str]:
    chunks = []
    for page in PdfReader(path).pages:
        text = _page_text(page)
        if text.strip():
            chunks.extend(splitter.split_text(text))
    return chunks


def embed_texts(texts: list[str]) -> list[list[float]]:
    response = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [item.embedding for item in response.data]
