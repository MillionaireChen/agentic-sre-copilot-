"""Ingest knowledge documents into pgvector.

Markdown files are ingested directly. PDF/Office documents are first
converted to Markdown with MinerU (run in its own venv):

    /var/tmp/fls/sre/mineru-venv/bin/mineru -p doc.pdf -o out/

Usage: python -m backend.rag.ingest [knowledge_dir]
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from backend.db.session import SessionLocal, init_db
from backend.db.models import RunbookChunk
from backend.rag.embeddings import embed_texts

MINERU_BIN = "/var/tmp/fls/sre/mineru-venv/bin/mineru"

CHUNK_CHARS = 2400   # ~600 tokens
OVERLAP_CHARS = 400  # ~100 tokens


def extract_markdown(path: Path) -> str:
    """Return markdown content for a document, using MinerU for non-md files."""
    if path.suffix.lower() in (".md", ".markdown", ".txt"):
        return path.read_text()
    with tempfile.TemporaryDirectory() as td:
        subprocess.run([MINERU_BIN, "-p", str(path), "-o", td], check=True)
        mds = list(Path(td).rglob("*.md"))
        if not mds:
            raise RuntimeError(f"MinerU produced no markdown for {path}")
        return "\n\n".join(m.read_text() for m in mds)


def chunk_markdown(text: str) -> list[tuple[str, str]]:
    """Split by ## sections, then window long sections. Returns (section, chunk)."""
    parts = re.split(r"(?m)^(#{1,2} .*)$", text)
    sections: list[tuple[str, str]] = []
    current = "intro"
    for p in parts:
        if re.match(r"^#{1,2} ", p or ""):
            current = p.lstrip("# ").strip()
        elif p and p.strip():
            sections.append((current, p.strip()))
    chunks = []
    for section, body in sections:
        text_block = f"{section}\n{body}"
        if len(text_block) <= CHUNK_CHARS:
            chunks.append((section, text_block))
        else:
            i = 0
            while i < len(text_block):
                chunks.append((section, text_block[i:i + CHUNK_CHARS]))
                i += CHUNK_CHARS - OVERLAP_CHARS
    return chunks


def ingest(knowledge_dir: Path):
    init_db()
    docs = [p for p in knowledge_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in
            (".md", ".markdown", ".txt", ".pdf", ".docx", ".pptx")]
    print(f"ingesting {len(docs)} documents from {knowledge_dir}")
    with SessionLocal() as db:
        db.query(RunbookChunk).delete()
        for doc in docs:
            md = extract_markdown(doc)
            chunks = chunk_markdown(md)
            vecs = embed_texts([c for _, c in chunks])
            for (section, content), vec in zip(chunks, vecs):
                db.add(RunbookChunk(
                    document_name=doc.name, section=section, content=content,
                    embedding=vec, meta={"path": str(doc)}))
            print(f"  {doc.name}: {len(chunks)} chunks")
        db.commit()


if __name__ == "__main__":
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parents[2] / "knowledge")
    ingest(d)
