"""Text chunking with page and paragraph tracking."""

import re


def chunk_text(
    text: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    page_breaks: list[int] | None = None,
) -> list[dict]:
    """Split text into overlapping chunks with sentence-boundary preservation."""
    if not text or not text.strip():
        return []

    text = re.sub(r'\s+', ' ', text).strip()

    if len(text) <= chunk_size:
        return [{"text": text, "start_page": 1, "end_page": 1}]

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        if end < len(text):
            search_start = start + int(chunk_size * 0.8)
            search_text = text[search_start:end]
            for sep in ['. ', '? ', '! ', '\n\n', '\n']:
                last_sep = search_text.rfind(sep)
                if last_sep != -1:
                    end = search_start + last_sep + len(sep)
                    break

        chunk_content = text[start:end].strip()

        if chunk_content:
            start_page = None
            end_page = None
            if page_breaks:
                for i, pb in enumerate(page_breaks):
                    if pb <= start:
                        start_page = i + 1
                    if pb <= end:
                        end_page = i + 1

            chunks.append({
                "text": chunk_content,
                "start_page": start_page,
                "end_page": end_page,
            })

        start = end - chunk_overlap
        if start >= len(text) - chunk_overlap:
            break

    return chunks


def chunk_by_paragraphs(
    text: str,
    max_chunk_size: int = 1500,
    min_chunk_size: int = 200,
) -> list[dict]:
    """Split text into chunks by paragraph boundaries."""
    if not text or not text.strip():
        return []

    paragraphs = re.split(r'\n\s*\n', text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    if not paragraphs:
        return []

    chunks = []
    current_chunk = ""
    current_para_idx = 0

    for i, para in enumerate(paragraphs):
        if len(para) > max_chunk_size:
            if current_chunk:
                chunks.append({"text": current_chunk, "paragraph": current_para_idx})
                current_chunk = ""
            sub_chunks = chunk_text(para, chunk_size=max_chunk_size, chunk_overlap=100)
            for sc in sub_chunks:
                sc["paragraph"] = i
            chunks.extend(sub_chunks)
            current_para_idx = i + 1
            continue

        test_chunk = f"{current_chunk}\n\n{para}" if current_chunk else para

        if len(test_chunk) > max_chunk_size:
            if current_chunk:
                chunks.append({"text": current_chunk, "paragraph": current_para_idx})
            current_chunk = para
            current_para_idx = i
        else:
            current_chunk = test_chunk

    if current_chunk:
        chunks.append({"text": current_chunk, "paragraph": current_para_idx})

    return chunks
