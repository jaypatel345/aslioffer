import json
import re
from pathlib import Path
import pytest

CONTRACT_FIXTURES_DIR = (
    Path(__file__).resolve().parent.parent / "fixtures" / "investigation" / "extraction_contract"
)

ALLOWED_CLAIM_KINDS = {
    "claimed_employer",
    "recruiting_agency",
    "sender_recruiter",
    "candidate_contact",
    "meeting_platform",
    "job_role",
    "compensation",
    "payment_request",
    "credential_request",
    "interview_url",
    "application_destination",
    "official_domain_reference",
    "user_correction",
}

ALLOWED_EXTRACTION_STATUSES = {
    "extracted",
    "user_corrected",
    "ambiguous",
    "inferred",
}

ALLOWED_CONFIDENCE_TIERS = {
    "HIGH",
    "MEDIUM",
    "LOW",
}


def load_all_contract_examples():
    """Loads all extraction contract reference examples."""
    examples = []
    for file_path in sorted(CONTRACT_FIXTURES_DIR.glob("example_*.json")):
        with open(file_path, "r", encoding="utf-8") as f:
            examples.append(json.load(f))
    return examples


@pytest.fixture
def all_contract_examples():
    return load_all_contract_examples()


def test_contract_example_count(all_contract_examples):
    """Ensure at least six required reference examples are present."""
    assert len(all_contract_examples) >= 6, (
        f"Expected at least 6 contract examples, found {len(all_contract_examples)}"
    )


def test_contract_example_required_structure(all_contract_examples):
    """Ensure each example conforms to the top-level contract structure."""
    required_keys = ["contract_version", "example_id", "title", "description", "synthetic", "raw_text", "extraction"]
    for ex in all_contract_examples:
        eid = ex.get("example_id")
        for key in required_keys:
            assert key in ex, f"Missing required top-level key '{key}' in {eid}"

        assert ex["synthetic"] is True, f"Example {eid} must have synthetic=True"
        assert isinstance(ex["raw_text"], str) and len(ex["raw_text"]) > 0

        extraction = ex["extraction"]
        assert "source_type" in extraction, f"Missing 'source_type' in extraction for {eid}"
        assert "claims" in extraction, f"Missing 'claims' in extraction for {eid}"
        assert isinstance(extraction["claims"], list) and len(extraction["claims"]) > 0


def test_claim_ids_unique_within_example(all_contract_examples):
    """Claim IDs must be unique within each contract example."""
    for ex in all_contract_examples:
        eid = ex.get("example_id")
        claims = ex["extraction"]["claims"]
        claim_ids = [c["claim_id"] for c in claims]
        assert len(claim_ids) == len(set(claim_ids)), f"Duplicate claim IDs found in {eid}: {claim_ids}"


def test_claim_fields_and_allowed_states(all_contract_examples):
    """Claims must use recognized kinds, valid statuses, and confidence tiers."""
    for ex in all_contract_examples:
        eid = ex.get("example_id")
        for claim in ex["extraction"]["claims"]:
            cid = claim.get("claim_id")
            assert claim.get("kind") in ALLOWED_CLAIM_KINDS, (
                f"Invalid claim kind '{claim.get('kind')}' in {eid} / {cid}"
            )
            assert claim.get("extraction_status") in ALLOWED_EXTRACTION_STATUSES, (
                f"Invalid extraction_status '{claim.get('extraction_status')}' in {eid} / {cid}"
            )
            assert claim.get("confidence_tier") in ALLOWED_CONFIDENCE_TIERS, (
                f"Invalid confidence_tier '{claim.get('confidence_tier')}' in {eid} / {cid}"
            )
            assert isinstance(claim.get("attributes"), dict), f"attributes must be dict in {eid} / {cid}"


def test_supplied_offsets_reproduce_quote_exactly(all_contract_examples):
    """When source_span is supplied, raw_text[start:end] must strictly match source_quote."""
    for ex in all_contract_examples:
        eid = ex.get("example_id")
        raw_text = ex["raw_text"]
        for claim in ex["extraction"]["claims"]:
            cid = claim.get("claim_id")
            span = claim.get("source_span")
            quote = claim.get("source_quote")

            if span is not None:
                assert quote is not None, f"source_quote cannot be null when source_span is provided in {eid} / {cid}"
                start = span.get("start_offset")
                end = span.get("end_offset")
                assert isinstance(start, int) and isinstance(end, int), f"Offsets must be integers in {eid} / {cid}"
                assert 0 <= start <= end <= len(raw_text), (
                    f"Offset range [{start}, {end}] out of bounds (len={len(raw_text)}) in {eid} / {cid}"
                )

                extracted_slice = raw_text[start:end]
                assert extracted_slice == quote, (
                    f"Offset mismatch in {eid} / {cid}: expected quote '{quote}', but raw_text[{start}:{end}] is '{extracted_slice}'"
                )
            else:
                # If span is None, quote must also be None (e.g. user corrections)
                assert quote is None, (
                    f"source_quote must be null when source_span is null in {eid} / {cid}"
                )


def test_user_corrections_distinguishable_from_source(all_contract_examples):
    """User corrections must not masquerade as document quotes and must have attribution metadata."""
    for ex in all_contract_examples:
        eid = ex.get("example_id")
        for claim in ex["extraction"]["claims"]:
            cid = claim.get("claim_id")
            if claim.get("extraction_status") == "user_corrected":
                # Must NOT claim to be a document quote
                assert claim.get("source_span") is None, (
                    f"User correction {cid} in {eid} must have source_span=None"
                )
                assert claim.get("source_quote") is None, (
                    f"User correction {cid} in {eid} must have source_quote=None"
                )
                # Must provide attribution in attributes
                attrs = claim.get("attributes", {})
                assert "attribution" in attrs, (
                    f"User correction {cid} in {eid} must contain 'attribution' in attributes"
                )
                assert attrs["attribution"].get("source") == "user_interactive_confirmation"


def test_safety_and_omitted_secrets(all_contract_examples):
    """Verify that credentials / OTP secrets are omitted, and no live credentials exist."""
    forbidden_patterns = [
        r"AIzaSy[A-Za-z0-9_-]{33}",
        r"ghp_[A-Za-z0-9]{36}",
        r"sk-[a-zA-Z0-9_-]{20,}",
        r"Bearer\s+[A-Za-z0-9._-]{20,}",
    ]
    for ex in all_contract_examples:
        content_str = json.dumps(ex)
        for pattern in forbidden_patterns:
            assert not re.search(pattern, content_str), (
                f"Forbidden pattern '{pattern}' matched in {ex.get('example_id')}"
            )

        # In credential requests, secret values must be null/omitted
        for claim in ex["extraction"]["claims"]:
            if claim.get("kind") == "credential_request":
                attrs = claim.get("attributes", {})
                assert attrs.get("secret_values_omitted") is True, (
                    f"secret_values_omitted must be true in {ex.get('example_id')}"
                )
                assert attrs.get("secret_payload") is None, (
                    f"secret_payload must be null in {ex.get('example_id')}"
                )
