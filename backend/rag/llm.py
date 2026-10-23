"""Groq LLM client wrapper with graceful error handling.

Reads the API key from Streamlit secrets or the environment. Returns a
structured result with answer, sources, grounded flag, and error message.
Catches authentication, rate-limit, and timeout errors into clean messages.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
import os
import sys
from typing import Any

from backend.rag.config import DEFAULT_MAX_TOKENS, LLM_FALLBACK_MODEL, LLM_MODEL
from backend.rag.prompter import PromptBundle
from backend.rag.retriever import RetrievedChunk


@dataclass
class LlmResponse:
    answer: str
    sources: list[str] = field(default_factory=list)
    grounded: bool = True
    error: str | None = None
    model: str = LLM_MODEL


@dataclass(frozen=True)
class GroqPackageStatus:
    available: bool
    message: str | None = None
    interpreter: str = sys.executable


def _import_groq_symbols() -> tuple[Any, ...]:
    """Import exactly the Groq symbols used by the completion client."""
    from groq import (
        APIConnectionError,
        APITimeoutError,
        AuthenticationError,
        BadRequestError,
        Groq,
        NotFoundError,
        RateLimitError,
    )

    return (
        Groq,
        APIConnectionError,
        APITimeoutError,
        AuthenticationError,
        BadRequestError,
        NotFoundError,
        RateLimitError,
    )


def get_package_status() -> GroqPackageStatus:
    """Report whether the installed Groq package supports the required client API."""
    try:
        _import_groq_symbols()
    except Exception as exc:
        return GroqPackageStatus(
            available=False,
            message=(
                "The Groq Python package is missing or incompatible "
                f"({type(exc).__name__}: {exc}). Install it with "
                f"`{sys.executable} -m pip install groq`."
            ),
        )
    return GroqPackageStatus(available=True)


_PLACEHOLDER_PREFIXES = ("your_", "xxx", "sk-", "replace", "insert", "put_", "<")


def _is_real_key(value: str | None) -> bool:
    """Return True only for non-empty strings that don't look like a template placeholder."""
    if not value:
        return False
    v = value.strip().lower()
    if not v or v in {"", '""', "''", "null", "none", "changeme", "todo"}:
        return False
    if any(v.startswith(p) for p in _PLACEHOLDER_PREFIXES):
        return False
    return True


def _get_api_key() -> str | None:
    """Read the Groq API key from Streamlit secrets or the environment.

    Returns None when no key is set or when the value is still the template
    placeholder, so the UI shows the 'not configured' message instead of
    attempting an API call that would fail with an authentication error.
    """
    candidate: str | None = None
    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            candidate = st.secrets.get("GROQ_API_KEY")
    except Exception:
        pass
    if not _is_real_key(candidate):
        candidate = os.environ.get("GROQ_API_KEY")
    if _is_real_key(candidate):
        return candidate.strip()
    return None


def _call_groq(system: str, user_message: str) -> tuple[str | None, str | None, str]:
    """Invoke the Groq chat completions API.

    Returns (answer, error, model_used). On a 404 for the primary model,
    automatically retries with LLM_FALLBACK_MODEL so the advisor stays up
    when the primary model is unavailable to this account.
    """
    package_status = get_package_status()
    if not package_status.available:
        return None, package_status.message or "The Groq Python package is unavailable.", LLM_MODEL

    (
        Groq,
        APIConnectionError,
        APITimeoutError,
        AuthenticationError,
        BadRequestError,
        NotFoundError,
        RateLimitError,
    ) = _import_groq_symbols()

    api_key = _get_api_key()
    if not api_key:
        return None, "Groq API key is not configured. Set GROQ_API_KEY in .streamlit/secrets.toml or the environment.", LLM_MODEL

    def _attempt(model: str) -> tuple[str | None, str | None]:
        try:
            # Bound latency/retries so a stalled provider cannot hang the UI.
            client = Groq(api_key=api_key, timeout=25.0, max_retries=1)
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.1,
                max_tokens=DEFAULT_MAX_TOKENS,
            )
            message = completion.choices[0].message if completion.choices else None
            answer = getattr(message, "content", None) if message else None
            if not answer:
                return None, "The model returned an empty response."
            return answer.strip(), None
        except AuthenticationError:
            return None, "Groq API key is invalid or expired."
        except RateLimitError:
            return None, "Groq rate limit reached. Please try again in a moment."
        except APITimeoutError:
            return None, "Groq request timed out. Please try again."
        except APIConnectionError:
            return None, "Could not connect to Groq. Check your internet connection."
        except NotFoundError:
            return None, "__not_found__"
        except BadRequestError as exc:
            msg = str(exc)
            if "does not exist" in msg or "model_not_found" in msg.lower():
                return None, "__not_found__"
            return None, "Groq rejected the request. Check the configured model and provider settings."
        except Exception as exc:
            return None, f"Unexpected provider error ({type(exc).__name__})."

    answer, error = _attempt(LLM_MODEL)
    if error == "__not_found__" and LLM_FALLBACK_MODEL and LLM_FALLBACK_MODEL != LLM_MODEL:
        answer, error = _attempt(LLM_FALLBACK_MODEL)
        if error is None:
            return answer, None, LLM_FALLBACK_MODEL
        if error == "__not_found__":
            return None, f"Neither primary ({LLM_MODEL}) nor fallback ({LLM_FALLBACK_MODEL}) Groq model is available.", LLM_FALLBACK_MODEL
        return None, error, LLM_FALLBACK_MODEL
    if error == "__not_found__":
        return None, f"Groq model '{LLM_MODEL}' is not available to this account.", LLM_MODEL
    return answer, error, LLM_MODEL if error is None else LLM_MODEL


def generate(bundle: PromptBundle) -> LlmResponse:
    """Generate an answer from the prompt bundle."""
    if bundle.refused:
        return LlmResponse(
            answer=bundle.user_message,
            sources=[chunk.source_label for chunk in bundle.evidence],
            grounded=True,
            error=None,
        )

    answer, error, model_used = _call_groq(bundle.system, bundle.user_message)
    if error:
        return LlmResponse(answer="", sources=[], grounded=False, error=error, model=model_used)

    sources = [chunk.source_label for chunk in bundle.evidence]
    tagged = any(tag in answer for tag in ["[verified fact]", "[calculation]", "[recommendation]", "[uncertain]"])
    cited_indexes = {
        int(index)
        for index in re.findall(r"\[(\d+)\]", answer)
        if 1 <= int(index) <= len(sources)
    }
    grounded = tagged or bool(cited_indexes)

    return LlmResponse(answer=answer, sources=sources, grounded=grounded, error=None, model=model_used)


def is_available() -> bool:
    """Check whether the Groq client package and API key are available."""
    return get_package_status().available and _get_api_key() is not None
