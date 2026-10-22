from backend.rag.prompter import _current_question_contract, build_prompt, prune_profile
from backend.rag.retriever import wants_university_alternatives


def test_other_uni_options_phrase_is_comparison_intent():
    assert wants_university_alternatives("What about some other uni options for CS?")
    assert wants_university_alternatives("What alternatives do I have besides NUST?")


def test_alternatives_contract_overrides_old_action_plan():
    contract = _current_question_contract("What about some other uni options?")
    assert "UNIVERSITY ALTERNATIVES" in contract
    assert "earlier action plan" in contract
    assert "Do not respond with 'register again'" in contract


def test_build_prompt_keeps_latest_question_and_intent_explicit():
    bundle = build_prompt(
        question="What about some other uni options?",
        evidence=[],
        profile={"qualification": "ICS", "aggregate": 78, "target_university": "NUST"},
        eligibility={"verdict": "ELIGIBLE"},
        history=[
            {"role": "user", "content": "How do I register?"},
            {"role": "assistant", "content": "Register on the selected university portal."},
        ],
    )
    assert "What about some other uni options?" in bundle.user_message
    assert "CURRENT INTENT: UNIVERSITY ALTERNATIVES / COMPARISON" in bundle.user_message
    assert "Recent conversation" in bundle.user_message
    assert "qualification: ICS" not in bundle.user_message  # profile uses human-readable labels
    assert "Qualification: ICS" in bundle.user_message


def test_alternatives_question_keeps_academic_profile_context():
    profile = {
        "qualification": "ICS",
        "aggregate": 78,
        "ssc_percentage": 85,
        "hssc_percentage": 75,
        "target_university": "NUST",
        "target_program": "BS Computer Science",
        "documents": ["CNIC"],
        "test_scores": {"NET": 110},
    }
    pruned = prune_profile(profile, "What about some other uni options?")
    assert pruned["qualification"] == "ICS"
    assert pruned["target_university"] == "NUST"
    assert "documents" not in pruned
    assert "test_scores" not in pruned
