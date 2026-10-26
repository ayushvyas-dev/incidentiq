"""Validate supported uploads and extract their text."""

import json

import pymupdf


class UnsupportedDocument(ValueError):
    pass


class InvalidDocument(ValueError):
    pass


CONTENT_TYPES = {
    ".md": {"text/markdown", "text/x-markdown", "text/plain"},
    ".txt": {"text/plain"},
    ".jsonl": {"application/json", "application/jsonl", "application/x-ndjson", "text/plain"},
    ".pdf": {"application/pdf"},
}


def extract_text(filename: str, content_type: str | None, data: bytes) -> str:
    suffix = filename.rpartition(".")[2].lower()
    extension = f".{suffix}" if suffix else ""
    allowed_types = CONTENT_TYPES.get(extension)
    if allowed_types is None:
        raise UnsupportedDocument("Supported file types are .md, .txt, .pdf, and .jsonl")

    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if media_type not in allowed_types:
        raise UnsupportedDocument("File content type does not match its extension")
    if not data:
        raise InvalidDocument("The uploaded file is empty")

    if extension == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise InvalidDocument("The uploaded file is not a valid PDF")
        try:
            with pymupdf.open(stream=data, filetype="pdf") as document:
                if document.needs_pass:
                    raise InvalidDocument("Password-protected PDFs are not supported")
                text = "\n".join(page.get_text(sort=True) for page in document)
        except (pymupdf.FileDataError, ValueError) as error:
            if isinstance(error, InvalidDocument):
                raise
            raise InvalidDocument("The uploaded PDF could not be read") from error
        if not text.strip():
            # shortcut: rejects image-only PDFs, add OCR if scanned documents must be ingested.
            raise InvalidDocument("The PDF contains no extractable text")
        return text

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise InvalidDocument("Text documents must use UTF-8 encoding") from error

    if extension == ".jsonl":
        records = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise InvalidDocument(f"Invalid JSONL record on line {line_number}") from error
            records.append(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        text = "\n".join(records)

    if not text.strip():
        raise InvalidDocument("The uploaded file contains no text")
    return text
