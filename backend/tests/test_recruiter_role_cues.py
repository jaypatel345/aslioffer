"""Named hiring roles before an email attribute it to the recruiter, not to the candidate."""
import pytest

from app.services.extractor.claim_models import ClaimKind
from app.services.extractor.grounded_parser import GroundedEntityParser

RECRUITER = ClaimKind.SENDER_RECRUITER.value


def _email_kinds(text):
    result = GroundedEntityParser().parse(text, source_type="text")
    return {c.value: c.kind for c in result.claims if c.attributes.get("channel") == "email"}


@pytest.mark.parametrize("lead", [
    "For queries, contact your recruitment coordinator at",
    "Please write to our HR manager at",
    "Reach the hiring team at",
    "Your talent partner is",
])
def test_named_hiring_role_marks_recruiter_email(lead):
    kinds = _email_kinds(f"Employment Offer - Infosys Limited\n{lead} pooja.kulkarni@infosys.com.")
    assert kinds["pooja.kulkarni@infosys.com"] == RECRUITER


def test_candidate_email_is_still_candidate_contact():
    kinds = _email_kinds("Candidate email: priya.sharma@gmail.com\n"
                         "For queries, contact your recruitment coordinator at pooja.kulkarni@infosys.com.")
    # The candidate's own address is attributed to the candidate (and redacted).
    assert kinds["[REDACTED_CANDIDATE_EMAIL]"] == ClaimKind.CANDIDATE_CONTACT.value
    assert kinds["pooja.kulkarni@infosys.com"] == RECRUITER


def test_unlabelled_email_stays_ambiguous():
    kinds = _email_kinds("Employment Offer - Infosys Limited\nSee pooja.kulkarni@infosys.com for details.")
    assert kinds["pooja.kulkarni@infosys.com"] != RECRUITER
