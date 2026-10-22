"""Constants for the RAG advisor pipeline."""
from __future__ import annotations

from pathlib import Path

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
LLM_MODEL = "openai/gpt-oss-120b"
LLM_FALLBACK_MODEL = "openai/gpt-oss-20b"
COLLECTION_NAME = "edupath_policies"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_DIR = REPO_ROOT / ".rag_cache" / "chroma"
POLICIES_DIR = REPO_ROOT / "data" / "policies"
UNIVERSITIES_PATH = REPO_ROOT / "data" / "universities.json"

DEFAULT_K = 5
DEFAULT_MAX_TOKENS = 2048
MIN_UNIVERSITY_RESULTS = 2
MAX_HISTORY_TURNS = 4

MAX_CHUNK_CHARS = 1200
MIN_CHUNK_CHARS = 60

POLICY_CATEGORIES: tuple[str, ...] = (
    "eligibility",
    "aggregate",
    "admission_test",
    "documents",
    "deadline",
    "fees",
    "notes",
    "sources",
    "overview",
)

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "deadline": ("deadline", "apply by", "last date", "when"),
    "fees": ("fee", "tuition", "cost", "pkr", "price"),
    "documents": ("document", "required doc", "cnic", "domicile", "transcript"),
    "admission_test": ("entry test", "nat", "net", "ecat", "sat", "lcat", "test"),
    "eligibility": (
        "eligible",
        "eligibility",
        "qualify",
        "requirement",
        "criteria",
        "minimum",
    ),
    "aggregate": (
        "aggregate",
        "cutoff",
        "cut-off",
        "merit",
        "percentage",
        "hssc",
        "ssc",
    ),
}

PROFILE_SLICE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "academic": ("eligible", "aggregate", "cutoff", "merit", "qualify", "requirement"),
    "documents": ("document", "cnic", "domicile", "transcript", "photo"),
    "test": ("entry test", "nat", "net", "ecat", "sat", "lcat", "test score"),
}


# Canonical university_id -> list of lowercase aliases used for intent filtering.
# The alias table is the authoritative source for abbreviations and alternative
# spellings (FAST, FAST-NUCES, NUST, LUMS, ...). data_loader aliases are also
# merged in at runtime so newly-added universities still match by name.
UNIVERSITY_ALIASES: dict[str, tuple[str, ...]] = {
    "fast-nuces": ("fast", "fast-nuces", "fast nuances", "nuces"),
    "nust": ("nust", "national university of sciences and technology"),
    "lums": ("lums", "lahore university of management sciences"),
    "comsats": ("comsats", "comsats university islamabad"),
    "uet": ("uet", "university of engineering and technology lahore"),
    "muet": ("muet", "mehran university of engineering and technology"),
    "giki": ("giki", "ghulam ishaq khan institute", "ghulam ishaq khan institute of engineering sciences and technology"),
    "ned": ("ned", "ned university", "ned university of engineering and technology"),
    "university-of-karachi": ("uok", "university of karachi", "karachi university"),
    "punjab-university": ("pu", "punjab university", "university of the punjab"),
    "iba-karachi": ("iba", "iba karachi", "institute of business administration karachi"),
}
