"""University-aware policy retrieval with comparison-aware scope selection."""
from __future__ import annotations

from dataclasses import dataclass
import functools
import logging
import re
from typing import Any

from backend.data_loader import load_universities
from backend.rag.config import (
    CATEGORY_KEYWORDS,
    DEFAULT_K,
    MIN_UNIVERSITY_RESULTS,
    UNIVERSITY_ALIASES,
)
from backend.rag.indexer import build_collection, get_persistent_client

logger = logging.getLogger(__name__)

_COMPARISON_PATTERNS = (
    r"\bother\s+(?:universit(?:y|ies)|uni(?:s)?)\b",
    r"\b(?:another|alternative|alternatives|backup|similar)\s+(?:universit(?:y|ies)|uni(?:s)?|program(?:me)?|option(?:s)?)\b",
    r"\b(?:universit(?:y|ies)|uni(?:s)?)\s+options?\b",
    r"\bother\s+options?\b",
    r"\bcompare\b",
    r"\bcomparison\b",
    r"\bcompared\s+(?:with|to)\b",
    r"\bwhat\s+else\b",
    r"\belsewhere\b",
    r"\bother\s+than\b",
    r"\bapart\s+from\b",
    r"\bbesides\b",
    r"\binstead\s+of\b",
)


def wants_university_alternatives(question: str) -> bool:
    """True when the latest question asks to broaden beyond one selected program."""
    q = re.sub(r"\s+", " ", (question or "").casefold())
    return any(re.search(pattern, q) for pattern in _COMPARISON_PATTERNS)


@dataclass(frozen=True)
class RetrievedChunk:
    text: str
    university_id: str
    university_name: str
    program_id: str
    program_name: str
    category: str
    source_file: str
    distance: float

    @property
    def source_label(self) -> str:
        if self.program_id == "overview":
            return f"{self.university_name} (overview)"
        return f"{self.university_name} — {self.program_name}, {self.category}"


@functools.lru_cache(maxsize=1)
def _load_alias_table() -> dict[str, str]:
    """Build alias -> canonical university_id mapping from config and catalog."""
    merged: dict[str, str] = {}
    try:
        data = load_universities()
    except Exception:
        data = {"universities": []}

    for uni in data.get("universities", []) or []:
        uid = uni.get("id", "")
        if not uid:
            continue
        for raw in (uni.get("id"), uni.get("name"), uni.get("full_name")):
            if raw:
                merged.setdefault(raw.strip().casefold(), uid)

    for uid, aliases in UNIVERSITY_ALIASES.items():
        for alias in aliases:
            merged[alias.strip().casefold()] = uid

    return merged


def _mentioned_university_ids(question: str, aliases: dict[str, str]) -> list[str]:
    q = (question or "").casefold()
    found: list[str] = []
    for alias in sorted(aliases, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", q):
            uid = aliases[alias]
            if uid not in found:
                found.append(uid)
    return found


def detect_intent(question: str) -> dict[str, Any]:
    q = (question or "").casefold()
    aliases = _load_alias_table()
    mentioned_ids = _mentioned_university_ids(q, aliases)

    detected_id: str | None = mentioned_ids[0] if mentioned_ids else None
    detected_name: str | None = None
    if detected_id is not None:
        try:
            data = load_universities()
            for uni in data.get("universities", []) or []:
                if uni.get("id") == detected_id:
                    detected_name = uni.get("name", detected_id)
                    break
        except Exception:
            detected_name = detected_id
        if detected_name is None:
            detected_name = detected_id

    detected_category: str | None = None
    best_hits = 0
    for category, keywords in CATEGORY_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in q)
        if hits > best_hits:
            best_hits = hits
            detected_category = category

    return {
        "university_id": detected_id,
        "university_name": detected_name,
        "university_ids": mentioned_ids,
        "category": detected_category,
        "compare_universities": wants_university_alternatives(q),
    }


class Retriever:
    """University-aware retriever.

    A named university in the latest question overrides the current UI selection.
    Alternative/comparison questions deliberately widen retrieval and request a
    representative result from each relevant university instead of pinning to
    the selected university.
    """

    def __init__(self, collection: Any) -> None:
        self._collection = collection

    def retrieve(
        self,
        question: str,
        k: int = DEFAULT_K,
        university_id: str | None = None,
    ) -> list[RetrievedChunk]:
        intent = detect_intent(question)
        mentioned = intent["university_ids"]
        compare = bool(intent["compare_universities"])

        if compare:
            aliases = _load_alias_table()
            all_ids = list(dict.fromkeys(aliases.values()))
            q = (question or "").casefold()
            # "Options besides NUST" should exclude the named comparison anchor.
            excludes_named_anchor = bool(
                mentioned
                and re.search(r"\b(?:other\s+than|apart\s+from|besides|instead\s+of)\b", q)
            )
            if len(mentioned) >= 2:
                candidate_ids = mentioned
            elif excludes_named_anchor:
                candidate_ids = [uid for uid in all_ids if uid not in set(mentioned)]
            elif not mentioned and university_id:
                candidate_ids = [uid for uid in all_ids if uid != university_id]
            else:
                candidate_ids = all_ids

            # A one-result query per university makes comparison retrieval diverse
            # even when the vector store otherwise returns only the selected school.
            results: list[RetrievedChunk] = []
            for uid in candidate_ids:
                try:
                    hits = self._collection.query(
                        query_texts=[question],
                        n_results=1,
                        where={"university_id": uid},
                    )
                    items = _materialize(hits)
                    if items:
                        results.append(items[0])
                except Exception as exc:
                    logger.debug("Comparison retrieval skipped for %s (%s)", uid, type(exc).__name__)

            if len(results) < min(k, 2):
                try:
                    broad = self._collection.query(query_texts=[question], n_results=k)
                    seen = {(r.university_id, r.program_id, r.category) for r in results}
                    for chunk in _materialize(broad):
                        key = (chunk.university_id, chunk.program_id, chunk.category)
                        if key not in seen:
                            results.append(chunk)
                            seen.add(key)
                except Exception as exc:
                    logger.warning("Comparison-wide retrieval failed (%s)", type(exc).__name__)

            if intent["category"]:
                results.sort(key=lambda c: (0 if c.category == intent["category"] else 1, c.distance))
            return results[:k]

        # For a normal follow-up, explicitly named university takes priority over
        # the dropdown selection. Otherwise preserve the selected-school context.
        effective_uni = intent["university_id"] or university_id
        results: list[RetrievedChunk] = []

        if effective_uni:
            try:
                hits = self._collection.query(
                    query_texts=[question],
                    n_results=k,
                    where={"university_id": effective_uni},
                )
                results.extend(_materialize(hits))
            except Exception as exc:
                logger.warning("University-scoped retrieval failed (%s)", type(exc).__name__)
                results = []

        if len(results) < MIN_UNIVERSITY_RESULTS:
            try:
                broad = self._collection.query(query_texts=[question], n_results=k)
                seen = {(r.university_id, r.program_id, r.category) for r in results}
                for chunk in _materialize(broad):
                    key = (chunk.university_id, chunk.program_id, chunk.category)
                    if key not in seen:
                        results.append(chunk)
                        seen.add(key)
            except Exception as exc:
                logger.error("Broad retrieval fallback failed (%s)", type(exc).__name__)

        if intent["category"] and len(results) > 1:
            results.sort(key=lambda c: (0 if c.category == intent["category"] else 1, c.distance))

        return results[:k]


def _materialize(hits: dict[str, Any]) -> list[RetrievedChunk]:
    ids = hits.get("ids", [[]])[0]
    documents = hits.get("documents", [[]])[0]
    metadatas = hits.get("metadatas", [[]])[0]
    distances = hits.get("distances", [[]])[0] if hits.get("distances") else [0.0] * len(ids)
    out: list[RetrievedChunk] = []
    for i, doc_id in enumerate(ids):
        meta = metadatas[i] if i < len(metadatas) else {}
        out.append(
            RetrievedChunk(
                text=documents[i] if i < len(documents) else "",
                university_id=meta.get("university_id", ""),
                university_name=meta.get("university_name", ""),
                program_id=meta.get("program_id", ""),
                program_name=meta.get("program_name", ""),
                category=meta.get("category", ""),
                source_file=meta.get("source_file", ""),
                distance=float(distances[i]) if i < len(distances) else 0.0,
            )
        )
    return out


def get_retriever(collection: Any | None = None) -> Retriever:
    if collection is None:
        collection = build_collection(get_persistent_client())
    return Retriever(collection)


def retrieve(
    question: str,
    k: int = DEFAULT_K,
    university_id: str | None = None,
) -> list[RetrievedChunk]:
    return get_retriever().retrieve(question, k=k, university_id=university_id)
