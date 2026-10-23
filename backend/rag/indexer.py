"""Index synthesized policy files into ChromaDB.

One chunk per markdown section. No cross-section merging, so a deadline
never lands inside an eligibility chunk. Chunks carry metadata used by
the retriever for university/category filtering.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

from backend.rag.config import (
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    INDEX_DIR,
    MAX_CHUNK_CHARS,
    MIN_CHUNK_CHARS,
    POLICIES_DIR,
)


@dataclass(frozen=True)
class PolicyChunk:
    university_id: str
    university_name: str
    program_id: str
    program_name: str
    category: str
    source_file: str
    text: str


def _split_sections(
    text: str,
    university_id: str,
    university_name: str,
    program_id: str,
    program_name: str,
    source_file: str,
) -> list[PolicyChunk]:
    sections: list[tuple[str, str]] = []
    current_title = "preamble"
    current_body: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current_body:
                sections.append((current_title, "\n".join(current_body)))
            current_title = line[3:].strip()
            current_body = []
        else:
            current_body.append(line)
    if current_body:
        sections.append((current_title, "\n".join(current_body)))

    title_to_category = {
        "Eligibility": "eligibility",
        "Aggregate": "aggregate",
        "Admission Test": "admission_test",
        "Required Documents": "documents",
        "Deadline": "deadline",
        "Fees": "fees",
        "Notes": "notes",
        "Sources": "sources",
        "Description": "overview",
        "Programs Offered": "overview",
        "Sources and Verification": "overview",
        "Disclaimer": "overview",
    }

    chunks: list[PolicyChunk] = []
    for title, body in sections:
        body = body.strip()
        if len(body) < MIN_CHUNK_CHARS:
            continue
        category = title_to_category.get(title, "notes")
        if len(body) > MAX_CHUNK_CHARS:
            parts = body.split("\n\n")
            buffer: list[str] = []
            buffer_len = 0
            for part in parts:
                piece = part.strip()
                if not piece:
                    continue
                if buffer_len + len(piece) + 2 > MAX_CHUNK_CHARS and buffer:
                    chunks.append(
                        PolicyChunk(
                            university_id=university_id,
                            university_name=university_name,
                            program_id=program_id,
                            program_name=program_name,
                            category=category,
                            source_file=source_file,
                            text="\n\n".join(buffer),
                        )
                    )
                    buffer = [piece]
                    buffer_len = len(piece)
                else:
                    buffer.append(piece)
                    buffer_len += len(piece) + 2
            if buffer:
                body = "\n\n".join(buffer)
            else:
                body = body[:MAX_CHUNK_CHARS]
        chunks.append(
            PolicyChunk(
                university_id=university_id,
                university_name=university_name,
                program_id=program_id,
                program_name=program_name,
                category=category,
                source_file=source_file,
                text=body,
            )
        )
    return chunks


def _doc_id(chunk: PolicyChunk) -> str:
    key = (
        f"{chunk.university_id}|{chunk.program_id}|{chunk.category}|"
        f"{chunk.source_file}|{hashlib.sha256(chunk.text.encode('utf-8')).hexdigest()[:16]}"
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


_embedding_fn_cache: Any | None = None


def _embedding_function() -> Any:
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    global _embedding_fn_cache
    if _embedding_fn_cache is not None:
        return _embedding_fn_cache
    _embedding_fn_cache = SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)
    return _embedding_fn_cache


_client_cache: Any | None = None


def get_persistent_client() -> Any:
    import chromadb

    global _client_cache
    if _client_cache is not None:
        return _client_cache

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    _client_cache = chromadb.PersistentClient(path=str(INDEX_DIR))
    return _client_cache


def build_collection(client: Any | None = None) -> Any:
    c = client or get_persistent_client()
    return c.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )


def _parse_front_matter(text: str, filename: Path) -> dict[str, str]:
    university_name = ""
    program_name = ""
    first_line = text.splitlines()[0] if text.splitlines() else ""
    if first_line.startswith("# "):
        head = first_line[2:]
        if " — " in head:
            university_name, program_name = head.split(" — ", 1)
        else:
            university_name = head
            program_name = filename.stem
    return {
        "university_name": university_name.strip(),
        "program_name": program_name.strip() or filename.stem,
    }


def index_policies(
    policies_dir: Path | None = None,
    collection: Any | None = None,
    force: bool = False,
) -> dict[str, int]:
    src_dir = policies_dir or POLICIES_DIR
    if not src_dir.exists():
        return {"indexed": 0, "skipped": 0, "files": 0}

    collection = collection if collection is not None else build_collection()

    existing_ids: set[str] = set()
    if force:
        # A force rebuild must remove old content first; merely adding new IDs
        # leaves stale policies in Chroma and can surface conflicting criteria.
        try:
            old_ids = list(collection.get().get("ids", []))
            for offset in range(0, len(old_ids), 500):
                collection.delete(ids=old_ids[offset:offset + 500])
        except Exception as exc:
            raise RuntimeError(
                "Forced policy re-index aborted because existing chunks could not be cleared."
            ) from exc
    else:
        try:
            count = collection.count()
            if count > 0:
                existing_ids = set(collection.get()["ids"])
        except Exception:
            existing_ids = set()

    indexed = 0
    skipped = 0
    files = 0
    for policy_file in sorted(src_dir.rglob("*.txt")):
        files += 1
        parts = policy_file.relative_to(src_dir).parts
        if len(parts) < 2:
            continue
        university_id = parts[0]
        program_id = policy_file.stem
        text = policy_file.read_text(encoding="utf-8")
        meta = _parse_front_matter(text, policy_file)
        relative = str(policy_file.relative_to(src_dir))

        chunks = _split_sections(
            text=text,
            university_id=university_id,
            university_name=meta["university_name"],
            program_id=program_id,
            program_name=meta["program_name"],
            source_file=f"data/policies/{relative}",
        )

        new_ids: list[str] = []
        new_docs: list[str] = []
        new_meta: list[dict[str, str]] = []
        for chunk in chunks:
            doc_id = _doc_id(chunk)
            if doc_id in existing_ids:
                skipped += 1
                continue
            new_ids.append(doc_id)
            new_docs.append(chunk.text)
            new_meta.append(
                {
                    "university_id": chunk.university_id,
                    "university_name": chunk.university_name,
                    "program_id": chunk.program_id,
                    "program_name": chunk.program_name,
                    "category": chunk.category,
                    "source_file": chunk.source_file,
                }
            )

        if new_ids:
            collection.add(ids=new_ids, documents=new_docs, metadatas=new_meta)
            indexed += len(new_ids)
            existing_ids.update(new_ids)

    return {"indexed": indexed, "skipped": skipped, "files": files}


if __name__ == "__main__":  # pragma: no cover
    result = index_policies()
    print(
        f"Indexed {result['indexed']} chunks "
        f"(skipped {result['skipped']}) from {result['files']} files."
    )
