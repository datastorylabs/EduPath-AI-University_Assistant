"""RAG advisor package entry point.

Exports:
    ask(question, profile, eligibility, history) -> AskResult
    build_index(force: bool = False) -> BuildResult
    is_available() -> bool
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from backend.rag import llm
from backend.rag.alternatives import answer_alternative_universities
from backend.rag.config import DEFAULT_K
from backend.rag.indexer import build_collection, get_persistent_client, index_policies
from backend.rag.policy_synthesis import synthesize_policy_files
from backend.rag.prompter import build_prompt
from backend.rag.retriever import (
    RetrievedChunk,
    get_retriever,
    wants_university_alternatives,
)


@dataclass
class AskResult:
    answer: str
    sources: list[str] = field(default_factory=list)
    evidence: list[RetrievedChunk] = field(default_factory=list)
    grounded: bool = True
    error: str | None = None
    engine: str = "rag"
    model: str | None = None


@dataclass
class BuildResult:
    synthesized_files: int = 0
    indexed_chunks: int = 0
    new_chunks: int = 0
    error: str | None = None


def ask(
    question: str,
    profile: dict[str, Any] | None = None,
    eligibility: dict[str, Any] | None = None,
    history: list[dict[str, str]] | None = None,
    k: int = DEFAULT_K,
    university_id: str | None = None,
    program_id: str | None = None,
) -> AskResult:
    """Run the RAG pipeline and return a grounded answer.

    The latest question determines the retrieval scope. In particular, asking
    for alternatives deliberately widens retrieval beyond the dropdown's
    selected university. The selected IDs are retained only as conversational
    context and for the deterministic fallback.
    """
    profile = profile or {}
    retrieval_question = question
    if wants_university_alternatives(question):
        context_fields = []
        for key, label in (
            ("target_program", "target program"),
            ("target_university", "currently selected university"),
            ("qualification", "qualification"),
            ("aggregate", "recorded aggregate"),
            ("hssc_group", "HSSC group"),
        ):
            value = profile.get(key)
            if value not in (None, ""):
                context_fields.append(f"{label}: {value}")
        if context_fields:
            retrieval_question = (
                question
                + "\n\nComparison retrieval context (use this only to retrieve relevant evidence): "
                + "; ".join(context_fields)
                + ". Search across universities, not just the selected university."
            )

    try:
        retriever = get_retriever()
        evidence = retriever.retrieve(retrieval_question, k=k, university_id=university_id)
    except Exception as exc:
        evidence = []
        retrieval_error = f"Retrieval failed: {type(exc).__name__}"
    else:
        retrieval_error = None

    bundle = build_prompt(
        question=question,
        evidence=evidence,
        profile=profile,
        eligibility=eligibility,
        history=history,
    )

    if not llm.is_available():
        fallback = _invoke_fallback(
            _rule_based_fallback,
            question, profile, eligibility,
            university_id=university_id, program_id=program_id,
        )
        return AskResult(
            answer=fallback,
            sources=[chunk.source_label for chunk in evidence],
            evidence=evidence,
            grounded=True,
            error=None,
            engine="rule-based",
            model=None,
        )

    response = llm.generate(bundle)
    if response.error:
        fallback = _invoke_fallback(
            _rule_based_fallback,
            question, profile, eligibility,
            university_id=university_id, program_id=program_id,
        )
        return AskResult(
            answer=fallback,
            sources=response.sources,
            evidence=evidence,
            grounded=True,
            error=response.error,
            engine="rule-based",
            model=response.model,
        )

    return AskResult(
        answer=response.answer,
        sources=response.sources,
        evidence=evidence,
        grounded=response.grounded,
        error=retrieval_error,
        engine="rag",
        model=response.model,
    )


def _rule_based_fallback(
    question: str,
    profile: dict[str, Any] | None,
    eligibility: dict[str, Any] | None,
    university_id: str | None = None,
    program_id: str | None = None,
) -> str:
    """Invoke a grounded catalog-based fallback when the LLM is unavailable."""
    profile = profile or {}
    eligibility = eligibility or {}

    if wants_university_alternatives(question):
        return answer_alternative_universities(
            question,
            profile,
            university_id or profile.get("target_university_id"),
            program_id or profile.get("target_program_id"),
        )

    try:
        from backend.advisor import answer_question
        from backend.data_loader import get_program, get_university, load_universities
    except ImportError:
        return "The AI advisor is not available. Please check your configuration."

    target_uni_id = university_id or profile.get("target_university_id")
    target_prog_id = program_id or profile.get("target_program_id")
    if not target_uni_id or not target_prog_id:
        return (
            "I can answer questions about the programs in EduPath's catalog. "
            "Tell me which university or program you are considering so I can retrieve its specific requirements."
        )

    try:
        data = load_universities()
        uni = get_university(data, target_uni_id)
        if uni is None:
            return "I could not find the selected university in the local catalog."
        program = get_program(uni, target_prog_id)
        if program is None:
            return "I could not find the selected program in the local catalog."
    except Exception:
        return "I could not read the local university catalog."

    return answer_question(question, profile, eligibility, program)


def _invoke_fallback(
    fallback_fn: Any,
    question: str,
    profile: dict[str, Any] | None,
    eligibility: dict[str, Any] | None,
    *,
    university_id: str | None,
    program_id: str | None,
) -> str:
    """Call older monkeypatched fallbacks without passing unsupported ID kwargs."""
    import inspect

    try:
        sig = inspect.signature(fallback_fn)
    except (TypeError, ValueError):
        sig = None

    accepts_ids = False
    if sig is not None:
        params = sig.parameters
        accepts_ids = (
            any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
            or "university_id" in params
            or "program_id" in params
        )

    if accepts_ids:
        return fallback_fn(
            question, profile, eligibility,
            university_id=university_id, program_id=program_id,
        )
    return fallback_fn(question, profile, eligibility)


def build_index(force: bool = False) -> BuildResult:
    """Synthesize policy files from JSON and index them into ChromaDB."""
    try:
        from backend.rag.config import POLICIES_DIR, UNIVERSITIES_PATH

        if force or not POLICIES_DIR.exists() or not list(POLICIES_DIR.glob("**/*.txt")):
            manifest = synthesize_policy_files(UNIVERSITIES_PATH, POLICIES_DIR)
            synthesized = len(manifest.get("files", [])) if isinstance(manifest, dict) else 0
        else:
            synthesized = len(list(POLICIES_DIR.glob("**/*.txt")))

        client = get_persistent_client()
        collection = build_collection(client)
        index_result = index_policies(policies_dir=POLICIES_DIR, collection=collection, force=force)

        return BuildResult(
            synthesized_files=synthesized,
            indexed_chunks=index_result.get("indexed", 0) + index_result.get("skipped", 0),
            new_chunks=index_result.get("indexed", 0),
            error=None,
        )
    except Exception as exc:
        return BuildResult(error=f"{type(exc).__name__}: {exc}")


def is_available() -> bool:
    return llm.is_available()


__all__ = ["ask", "build_index", "is_available", "AskResult", "BuildResult"]
