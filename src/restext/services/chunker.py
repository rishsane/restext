import hashlib
import re

import tiktoken

from restext.config import settings

_enc = tiktoken.encoding_for_model("gpt-4o")


def count_tokens(text: str) -> int:
    return len(_enc.encode(text))


def chunk_text(
    text: str,
    metadata: dict | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[dict]:
    """Split text into chunks with metadata.

    Returns list of {"content": str, "token_count": int, "content_hash": str, "metadata": dict, "chunk_index": int}
    """
    chunk_size = chunk_size or settings.chunk_size_tokens
    chunk_overlap = chunk_overlap or settings.chunk_overlap_tokens
    metadata = metadata or {}

    # Step 1: Split by markdown headers to get sections
    sections = _split_by_headers(text)

    chunks = []
    chunk_index = 0

    for section in sections:
        section_heading = section.get("heading", "")
        section_text = section["content"]

        # Step 2: Split sections into chunks via recursive character splitting
        section_chunks = _recursive_split(section_text, chunk_size, chunk_overlap)

        for chunk_text_piece in section_chunks:
            if not chunk_text_piece.strip():
                continue
            token_count = count_tokens(chunk_text_piece)
            if token_count < 10:  # Skip tiny fragments
                continue

            content_hash = hashlib.sha256(chunk_text_piece.encode()).hexdigest()
            chunk_meta = {**metadata}
            if section_heading:
                chunk_meta["section_heading"] = section_heading

            chunks.append({
                "content": chunk_text_piece,
                "token_count": token_count,
                "content_hash": content_hash,
                "metadata": chunk_meta,
                "chunk_index": chunk_index,
            })
            chunk_index += 1

    return chunks


def _split_by_headers(text: str) -> list[dict]:
    """Split text into sections based on markdown headers."""
    lines = text.split("\n")
    sections = []
    current_heading = ""
    current_lines = []

    for line in lines:
        if re.match(r"^#{1,4}\s+", line):
            if current_lines:
                sections.append({
                    "heading": current_heading,
                    "content": "\n".join(current_lines).strip(),
                })
            current_heading = re.sub(r"^#{1,4}\s+", "", line).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append({
            "heading": current_heading,
            "content": "\n".join(current_lines).strip(),
        })

    # If no headers found, return the whole text as one section
    if not sections:
        sections = [{"heading": "", "content": text.strip()}]

    return sections


def _recursive_split(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Recursively split text into chunks of ~chunk_size tokens with overlap."""
    token_count = count_tokens(text)
    if token_count <= chunk_size:
        return [text]

    # Try splitting by paragraphs first
    chunks = _split_by_separator(text, "\n\n", chunk_size, overlap)
    if chunks:
        return chunks

    # Then by sentences
    chunks = _split_by_separator(text, ". ", chunk_size, overlap)
    if chunks:
        return chunks

    # Finally by words (hard split)
    return _hard_split(text, chunk_size, overlap)


def _split_by_separator(text: str, separator: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text by separator and merge pieces into chunks."""
    pieces = text.split(separator)
    if len(pieces) <= 1:
        return []

    chunks = []
    current_pieces = []
    current_tokens = 0

    for piece in pieces:
        piece_with_sep = piece + separator
        piece_tokens = count_tokens(piece_with_sep)

        if current_tokens + piece_tokens > chunk_size and current_pieces:
            chunk_text = separator.join(current_pieces)
            chunks.append(chunk_text)

            # Keep overlap: take last pieces that fit in overlap tokens
            overlap_pieces = []
            overlap_tokens = 0
            for p in reversed(current_pieces):
                p_tokens = count_tokens(p)
                if overlap_tokens + p_tokens > overlap:
                    break
                overlap_pieces.insert(0, p)
                overlap_tokens += p_tokens

            current_pieces = overlap_pieces
            current_tokens = overlap_tokens

        current_pieces.append(piece)
        current_tokens += piece_tokens

    if current_pieces:
        chunks.append(separator.join(current_pieces))

    return chunks


def _hard_split(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text by encoding into tokens and decoding chunks."""
    tokens = _enc.encode(text)
    chunks = []
    start = 0

    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunk_tokens = tokens[start:end]
        chunk_text = _enc.decode(chunk_tokens)
        chunks.append(chunk_text)
        start = end - overlap

    return chunks
