"""KB loading and markdown chunking."""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from backend.embedder import embed_chunks

KB_DIR = Path("kb")
KB_CHUNKS_CACHE: Optional[List[dict]] = None


def slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-") or "chunk"


def strip_markdown(text: str) -> str:
    cleaned_lines = []
    for line in (text or "").splitlines():
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)
        line = re.sub(r"^\s*[-*+]\s+", "", line)
        line = re.sub(r"^\s*\d+\.\s+", "", line)
        cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"[`*_~]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def chunk_markdown(doc_id: str, text: str) -> List[dict]:
    """
    Split markdown on H2/H3 headings and return retrieval chunks.

    Each chunk includes:
      - chunk_id: "<filename>#<heading-slug>"
      - text: stripped markdown text
      - heading: H2/H3 text
      - doc_title: inherited H1 title
      - search_text: doc title + heading + text (normalized for matching)
    """
    lines = (text or "").splitlines()
    doc_title = Path(doc_id).stem.replace("_", " ").title()
    for line in lines:
        if line.strip().startswith("# "):
            doc_title = re.sub(r"^#\s+", "", line.strip()).strip() or doc_title
            break

    chunks: List[dict] = []
    slug_counts: dict[str, int] = {}
    current_heading: Optional[str] = None
    current_body: List[str] = []

    def flush_chunk() -> None:
        nonlocal current_heading, current_body
        if not current_heading:
            return

        raw_body = "\n".join(current_body).strip()
        raw_chunk = f"{current_heading}\n{raw_body}".strip()
        normalized_text = strip_markdown(raw_chunk)
        if not normalized_text:
            current_heading = None
            current_body = []
            return

        base_slug = slugify(current_heading)
        slug_counts[base_slug] = slug_counts.get(base_slug, 0) + 1
        slug = base_slug if slug_counts[base_slug] == 1 else f"{base_slug}-{slug_counts[base_slug]}"

        search_text = strip_markdown(f"{doc_title} {current_heading} {raw_body}").lower()
        chunks.append(
            {
                "doc_id": doc_id,
                "chunk_id": f"{doc_id}#{slug}",
                "text": normalized_text,
                "heading": current_heading,
                "doc_title": doc_title,
                "search_text": search_text,
            }
        )
        current_heading = None
        current_body = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") or stripped.startswith("### "):
            flush_chunk()
            current_heading = re.sub(r"^#{2,3}\s+", "", stripped).strip()
            current_body = []
            continue

        if current_heading is not None:
            current_body.append(line)

    flush_chunk()

    if not chunks:
        fallback_text = strip_markdown(text)
        if fallback_text:
            chunks.append(
                {
                    "doc_id": doc_id,
                    "chunk_id": f"{doc_id}#overview",
                    "text": fallback_text,
                    "heading": "Overview",
                    "doc_title": doc_title,
                    "search_text": strip_markdown(f"{doc_title} {fallback_text}").lower(),
                }
            )

    return chunks


def load_kb_chunks() -> List[dict]:
    if not KB_DIR.exists():
        return []
    all_chunks: List[dict] = []
    for path in sorted(KB_DIR.glob("*.md")):
        doc_id = path.name
        text = path.read_text(encoding="utf-8", errors="ignore")
        all_chunks.extend(chunk_markdown(doc_id, text))
    return all_chunks


def get_kb_chunks_cached(refresh: bool = False) -> List[dict]:
    global KB_CHUNKS_CACHE
    if KB_CHUNKS_CACHE is None or refresh:
        chunks = load_kb_chunks()
        if chunks:
            try:
                chunks = embed_chunks(chunks)
            except Exception as e:
                print(f"[Embedder] Failed to embed chunks, continuing with keyword retrieval only: {type(e).__name__}: {e}")
        KB_CHUNKS_CACHE = chunks
    return KB_CHUNKS_CACHE or []
