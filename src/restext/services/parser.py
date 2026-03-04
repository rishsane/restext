import os


def parse_file(file_path: str) -> str:
    """Parse a file and return its text content."""
    ext = os.path.splitext(file_path)[1].lower()

    if ext in (".txt", ".md"):
        return _parse_text(file_path)
    elif ext == ".pdf":
        return _parse_pdf(file_path)
    elif ext == ".docx":
        return _parse_docx(file_path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def _parse_text(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _parse_pdf(file_path: str) -> str:
    import fitz  # PyMuPDF

    text_parts = []
    with fitz.open(file_path) as doc:
        for page in doc:
            text = page.get_text()
            if text.strip():
                text_parts.append(text)
    return "\n\n".join(text_parts)


def _parse_docx(file_path: str) -> str:
    from docx import Document

    doc = Document(file_path)
    return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
