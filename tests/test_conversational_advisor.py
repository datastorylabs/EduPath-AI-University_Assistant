from backend.rag.alternatives import answer_alternative_universities
from backend.rag.prompter import build_prompt, prune_profile
from backend.rag.retriever import RetrievedChunk, Retriever, detect_intent, wants_university_alternatives


def test_other_university_options_is_detected_as_broad_intent():
    assert wants_university_alternatives("What about some other uni options?")
    assert detect_intent("Compare NUST and FAST")["compare_universities"] is True


def test_prompt_answers_latest_question_without_fixed_action_plan_template():
    chunk = RetrievedChunk(
        text="BS AI requires Mathematics and a minimum 50% HSSC.",
        university_id="fast-nuces",
        university_name="FAST-NUCES",
        program_id="bachelor-of-science-artificial-intelligence",
        program_name="BS Artificial Intelligence",
        category="eligibility",
        source_file="data/policies/fast-nuces/bs-ai.txt",
        distance=0.1,
    )
    bundle = build_prompt(
        "What other universities should I consider?",
        [chunk],
        profile={"qualification": "ICS", "aggregate": 72, "roll_number": "12345"},
        history=[
            {"role": "user", "content": "How do I register for the NET?"},
            {"role": "assistant", "content": "Register for the NET."},
        ],
    )
    assert "What other universities should I consider?" in bundle.user_message
    assert "CURRENT INTENT: UNIVERSITY ALTERNATIVES / COMPARISON" in bundle.user_message
    assert "register again" in bundle.user_message
    assert "exact structure for every answer" not in bundle.system.lower()
    assert "12345" not in bundle.user_message
    assert "Currently selected" not in _format_profile_text_for_test(bundle.user_message)


def _format_profile_text_for_test(prompt: str) -> str:
    return prompt

def test_explanation_question_gets_explanation_contract_not_action_plan():
    from backend.rag.prompter import _current_question_contract

    contract = _current_question_contract("Why does my qualification not match?")
    assert "CURRENT INTENT: EXPLANATION" in contract
    assert "action checklist" in contract


def test_alternatives_question_contract_prioritizes_student_concern():
    from backend.rag.prompter import _current_question_contract

    contract = _current_question_contract("What about some other uni options?")
    assert "CURRENT INTENT: UNIVERSITY ALTERNATIVES / COMPARISON" in contract
    assert "earlier action plan" in contract
    assert "register again" in contract

class FakeCollection:
    def __init__(self):
        self.calls = []

    def query(self, query_texts, n_results, where=None):
        self.calls.append({"question": query_texts[0], "n_results": n_results, "where": where})
        uid = (where or {}).get("university_id", "fast-nuces")
        name_map = {
            "nust": "NUST",
            "fast-nuces": "FAST-NUCES",
            "lums": "LUMS",
        }
        return {
            "ids": [[f"{uid}-1"]],
            "documents": [[f"Policy for {name_map.get(uid, uid)}." ]],
            "metadatas": [[{
                "university_id": uid,
                "university_name": name_map.get(uid, uid),
                "program_id": "overview",
                "program_name": "Overview",
                "category": "overview",
                "source_file": "fake.txt",
            }]],
            "distances": [[0.1]],
        }


def test_alternatives_retrieval_does_not_pin_to_selected_university(monkeypatch):
    import backend.rag.retriever as module

    monkeypatch.setattr(module, "_load_alias_table", lambda: {
        "nust": "nust", "fast": "fast-nuces", "lums": "lums"
    })
    collection = FakeCollection()
    results = Retriever(collection).retrieve(
        "What about some other uni options?", k=3, university_id="nust"
    )
    filtered_queries = [call for call in collection.calls if call["where"]]
    assert {call["where"]["university_id"] for call in filtered_queries} == {"fast-nuces", "lums"}
    assert "nust" not in {item.university_id for item in results}


def test_explicit_university_overrides_dropdown_selection(monkeypatch):
    import backend.rag.retriever as module

    monkeypatch.setattr(module, "_load_alias_table", lambda: {
        "nust": "nust", "fast": "fast-nuces"
    })
    collection = FakeCollection()
    Retriever(collection).retrieve("What about FAST eligibility?", k=3, university_id="nust")
    assert collection.calls[0]["where"] == {"university_id": "fast-nuces"}


def test_comparison_question_retrieves_all_named_universities(monkeypatch):
    import backend.rag.retriever as module

    monkeypatch.setattr(module, "_load_alias_table", lambda: {
        "nust": "nust", "fast": "fast-nuces", "lums": "lums"
    })
    collection = FakeCollection()
    Retriever(collection).retrieve("Compare NUST and FAST for computing.", k=3, university_id="lums")
    requested = {call["where"]["university_id"] for call in collection.calls if call["where"]}
    assert requested == {"nust", "fast-nuces"}


def test_alternative_fallback_provides_real_catalog_options_not_registration_boilerplate():
    catalog = {
        "universities": [
            {
                "id": "nust", "name": "NUST", "website": "https://nust.edu.pk",
                "programs": [{
                    "id": "bs-artificial-intelligence", "name": "BS Artificial Intelligence",
                    "category": "Computing",
                    "requirements": {"qualification": ["FSc Pre-Engineering"], "minimum_aggregate": 60}
                }]
            },
            {
                "id": "fast-nuces", "name": "FAST-NUCES", "website": "https://nu.edu.pk",
                "sources": [{"url": "https://nu.edu.pk/Admissions/EligibilityCriteria"}],
                "programs": [{
                    "id": "bachelor-of-science-artificial-intelligence", "name": "BS Artificial Intelligence",
                    "category": "Computing",
                    "requirements": {
                        "qualification": ["FSc Pre-Engineering"], "minimum_aggregate": 50,
                        "admission_test": "FAST-NUCES / SAT / NTS NAT-IE / NTS NAT-ICS",
                        "estimated_cutoff": None
                    }
                }]
            },
            {
                "id": "lums", "name": "LUMS", "website": "https://admission.lums.edu.pk",
                "sources": [{"url": "https://admission.lums.edu.pk/undergraduate-programmes"}],
                "programs": [{
                    "id": "bs-computer-science", "name": "BS Computer Science",
                    "category": "Computing",
                    "requirements": {
                        "qualification": ["FSc Pre-Engineering"], "minimum_aggregate": 60,
                        "estimated_cutoff": None
                    }
                }]
            }
        ]
    }
    answer = answer_alternative_universities(
        "What about some other uni options?",
        {"qualification": "FSc Pre-Engineering", "aggregate": 75},
        "nust",
        "bs-artificial-intelligence",
        universities_data=catalog,
        limit=5,
    )
    assert "FAST-NUCES" in answer
    assert "LUMS" in answer
    assert "Potential fit" in answer
    assert "Register for the NET" not in answer


def test_alternative_fallback_never_treats_missing_minimum_as_a_pass():
    catalog = {
        "universities": [
            {
                "id": "nust", "name": "NUST", "programs": [{
                    "id": "bs-ai", "name": "BS Artificial Intelligence",
                    "category": "Computing", "requirements": {"qualification": ["ICS"]}
                }]
            },
            {
                "id": "fast-nuces", "name": "FAST-NUCES", "website": "https://nu.edu.pk",
                "programs": [{
                    "id": "bs-cs", "name": "BS Computer Science", "category": "Computing",
                    "requirements": {"qualification": ["ICS"], "minimum_aggregate": None}
                }]
            }
        ]
    }
    answer = answer_alternative_universities(
        "What other university options do I have?",
        {"qualification": "ICS", "aggregate": 75},
        "nust",
        "bs-ai",
        universities_data=catalog,
    )
    assert "Possible option" in answer or "Needs checking" in answer
    assert "meet the catalog's listed baseline" not in answer
