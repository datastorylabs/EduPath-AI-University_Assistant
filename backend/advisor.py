"""AI advisor response generator.

The MVP uses rule-based, grounded explanations rather than a generic LLM so that
advice is always tied to the student's profile and the stored university data.
A real LLM can be swapped in later without changing the interface.
"""
from __future__ import annotations

from typing import Any


COMMON_ADVICE = {
    "nts-nat ie/ics": "Register for the NTS-NAT at https://www.nts.org.pk and select the IE/ICS category relevant to your program.",
    "nts-nat ie": "Register for the NTS-NAT at https://www.nts.org.pk and select the IE category.",
    "nust entry test (net)": "Register for the NET on the official NUST admissions portal and prepare using past papers and the NET syllabus.",
    "lcat / sat": "Register for the LUMS Common Admission Test (LCAT) through the LUMS admissions portal, or submit a valid SAT score if you have one.",
    "ecat (engineering college admission test)": "Register for ECAT through the UET admissions portal. Focus on FSc Math, Physics, Chemistry, and English.",
}


def explain_eligibility(result: dict[str, Any], program: dict[str, Any]) -> str:
    verdict = result["verdict"]
    program_name = f"{program['name']} at {program.get('university_name', 'the selected university')}"

    if verdict == "ELIGIBLE":
        opening = f"Great news — you appear eligible for **{program_name}** based on the information provided."
    elif verdict == "ELIGIBLE - Conditional":
        opening = (
            f"You meet the basic criteria for **{program_name}**, but there are "
            "one or more items you still need to complete before applying."
        )
    else:
        opening = (
            f"Based on the information provided, you do not currently meet the requirements for **{program_name}**. "
            "Here is exactly why, and what you can do about it."
        )

    parts = [opening, ""]

    # Key reasons
    parts.append("**Eligibility breakdown:**")
    for reason in result.get("reasons", []):
        parts.append(f"- {reason}")

    # Missing documents
    missing = result.get("missing_documents", [])
    if missing:
        parts.append("")
        parts.append("**Missing required documents:**")
        for doc in missing:
            parts.append(f"- {doc['name']}")

    # Test advice
    if result.get("test_missing") and result.get("admission_test"):
        test_name = result["admission_test"]
        advice = COMMON_ADVICE.get(test_name.lower(), "Check the university website for registration details.")
        parts.append("")
        parts.append(f"**Next step for admission test ({test_name}):** {advice}")

    # Deadline urgency
    days = result.get("days_remaining")
    if days is not None:
        parts.append("")
        if days < 0:
            parts.append("The deadline has already passed. Consider applying in the next admission cycle.")
        elif days <= 7:
            parts.append(f"Only {days} days left — prioritize completing missing items immediately.")
        elif days <= 30:
            parts.append(f"You have {days} days left. Aim to complete missing documents and tests within the next two weeks.")
        else:
            parts.append(f"You have {days} days until the deadline, which gives you time to prepare properly.")

    # Closing guidance
    if verdict == "NOT ELIGIBLE":
        parts.append("")
        parts.append(
            "If your aggregate or qualification can improve (e.g., retaking exams or adding a recognized equivalence), "
            "recheck eligibility after updating your profile. Otherwise, consider similar programs with lower cutoffs."
        )

    return "\n".join(parts)


def answer_question(question: str, profile: dict[str, Any], result: dict[str, Any], program: dict[str, Any]) -> str:
    """Answer the student's specific question from catalog and rule-check results."""
    q = " ".join(question.casefold().split())
    requirements = program.get("requirements", {}) or {}
    sources = program.get("university_sources", []) or []
    official_url = next(
        (
            source.get("url") for source in sources
            if source.get("url") and any(token in source["url"].casefold() for token in ("admission", "eligibility", "program", "policy"))
        ),
        program.get("university_website"),
    )

    def source_suffix() -> str:
        return f"\n\nOfficial source to confirm current-cycle details: {official_url}" if official_url else ""

    # Narrow deadline language; a generic "when" question is not necessarily
    # about application deadlines (it may ask about a test or merit list).
    deadline_phrases = (
        "deadline", "last date", "closing date", "due date", "application window",
        "when can i apply", "when does application", "when is the application",
        "when will applications", "when do applications", "application closes",
    )
    if any(phrase in q for phrase in deadline_phrases):
        deadline = result.get("application_deadline") or requirements.get("application_deadline")
        days = result.get("days_remaining")
        if deadline:
            suffix = f" ({days} days remaining)" if days is not None else ""
            return f"The stored application deadline for **{program['name']}** is **{deadline}**{suffix}.{source_suffix()}"
        return (
            f"EduPath does not have a verified application deadline recorded for **{program['name']}**. "
            "I don't want to give you a guessed date." + source_suffix()
        )

    # Test-related intent must be handled before broad eligibility language.
    test_terms = ("admission test", "entry test", "test", "register", "nts", "nat", "net", "ecat", "lcat", "sat")
    if any(term in q for term in test_terms):
        test = result.get("admission_test") or requirements.get("admission_test")
        if not test:
            return f"The required test route is not recorded for **{program['name']}**." + source_suffix()
        test_lower = str(test).casefold()
        advice = next(
            (value for key, value in COMMON_ADVICE.items() if key in test_lower or test_lower in key),
            None,
        )
        if any(phrase in q for phrase in ("register", "registration", "how do i sign up", "where do i apply")):
            advice = advice or "Use the official university admissions portal to confirm the current test registration process and dates."
            return f"For **{test}**, the catalog lists this route. {advice}{source_suffix()}"
        return f"For **{program['name']}**, the stored admission-test route is **{test}**. Check the official portal for current-cycle test options and dates." + source_suffix()

    # Distinguish documents asked for from documents actually missing.
    if any(term in q for term in ("missing document", "what documents", "which documents", "required documents", "document list", "cnic", "b-form", "transcript", "certificate")):
        required_docs = [
            item.get("name", "Unnamed document")
            for item in requirements.get("required_documents", []) or []
            if item.get("required", True)
        ]
        missing_docs = [
            item.get("name", "Unnamed document")
            for item in result.get("missing_documents", []) or []
        ]
        if "missing" in q:
            if missing_docs:
                return "Based on your current profile, these required documents are still missing: " + ", ".join(missing_docs) + "."
            return "No missing required documents are flagged by the current profile check. Confirm your uploaded copies are legible and complete."
        if required_docs:
            return "The catalog lists these required documents for **" + program["name"] + "**: " + ", ".join(required_docs) + "." + source_suffix()
        return f"The required document list isn't recorded for **{program['name']}** in the local catalog." + source_suffix()

    # Fees are a separate question; do not turn them into an eligibility/action plan.
    if any(term in q for term in ("fee", "tuition", "cost", "scholarship", "financial aid", "financial assistance")):
        fee = requirements.get("fee_estimate_pkr")
        if fee is not None:
            return f"The local catalog lists an estimated fee of PKR {fee:,} for **{program['name']}**. Treat it as an estimate and confirm the latest fee schedule." + source_suffix()
        return f"EduPath doesn't have a verified current fee figure recorded for **{program['name']}**. I won't guess the amount." + source_suffix()

    # Ask about eligibility specifically; "admission" alone must not trigger this.
    eligibility_terms = (
        "eligible", "eligibility", "am i qualified", "qualify for", "qualify",
        "admission chances", "chance of admission", "my chances", "verdict",
        "do i meet the criteria", "meet the requirement",
    )
    if any(term in q for term in eligibility_terms):
        return explain_eligibility(result, program)

    # Aggregate / merit questions should report the recorded values and avoid
    # implying a minimum threshold equals a likely admission.
    if any(term in q for term in ("aggregate", "percentage", "cutoff", "cut-off", "merit", "marks", "score", "weightage", "weighting")):
        aggregate = profile.get("aggregate")
        cutoff = result.get("estimated_cutoff") or requirements.get("estimated_cutoff")
        minimum = result.get("minimum_aggregate")
        if minimum is None:
            minimum = requirements.get("minimum_aggregate")
        agg_str = f"{aggregate}%" if aggregate is not None else "not recorded"
        cutoff_str = f"{cutoff}%" if cutoff is not None else "not available in EduPath"
        minimum_str = f"{minimum}%" if minimum is not None else "not available in EduPath"
        formula = requirements.get("aggregate_formula")
        reply = (
            f"Your recorded aggregate is **{agg_str}**. The catalog lists a minimum of **{minimum_str}** "
            f"and a closing-merit estimate of **{cutoff_str}** for **{program['name']}**. "
            "Meeting minimum eligibility is not a guarantee of selection."
        )
        if formula:
            reply += f" The stored merit formula is: {formula}."
        return reply + source_suffix()

    # Give catalog details for common programme/campus questions rather than
    # repeating an action-plan slogan.
    if any(term in q for term in ("duration", "how long", "years", "degree length")):
        duration = program.get("duration")
        if duration:
            return f"**{program['name']}** is listed as a {duration} programme." + source_suffix()
        return "The programme duration is not recorded in EduPath's local catalog." + source_suffix()

    if any(term in q for term in ("campus", "campuses", "location", "where is", "which city")):
        campuses = program.get("campuses") or program.get("university_campuses") or []
        if campuses:
            return f"The university lists these campuses: " + ", ".join(campuses) + ". Program availability may differ by campus." + source_suffix()
        return f"The local program record doesn't map **{program['name']}** to specific campuses. Confirm availability on the official programme list." + source_suffix()

    # Honest fallback: keep the user's topic in view and identify the exact data
    # gap instead of steering everyone back to eligibility or registration.
    topic = question.strip().rstrip("?.!") or "that question"
    return (
        f"I can't answer **{topic}** confidently from the information currently stored for **{program.get('name', 'this program')}**. "
        "That doesn't mean the answer is no—the detail may simply be missing from EduPath's local catalog."
        + source_suffix()
    )


def generate_action_plan(result: dict[str, Any], program: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a milestone-style action plan."""
    plan = []

    plan.append({
        "step": 1,
        "title": "Verify Academic Documents",
        "status": "completed" if not result.get("missing_documents") else "current_action",
        "description": "Upload and confirm FSc transcript, Matric certificate, and other academic records.",
    })

    test_name = (
        result.get("admission_test")
        or program.get("requirements", {}).get("admission_test")
        or "Admission Test"
    )

    if result.get("test_missing"):
        plan.append({
            "step": 2,
            "title": f"Register for {test_name}",
            "status": "current_action",
            "description": "Register, prepare, and upload your official score card.",
        })
        plan.append({
            "step": 3,
            "title": "Submit Application",
            "status": "upcoming",
            "description": "Complete the online application before the deadline.",
        })
    else:
        plan.append({
            "step": 2,
            "title": f"{test_name} Score Ready",
            "status": "completed",
            "description": "Your admission test score is recorded.",
        })
        plan.append({
            "step": 3,
            "title": "Submit Application",
            "status": "current_action",
            "description": "Complete the online application before the deadline.",
        })

    plan.append({
        "step": 4,
        "title": "Await Decision",
        "status": "upcoming",
        "description": "Track your application status on the university portal.",
    })

    return plan
