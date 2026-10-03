import json
import re
from pathlib import Path
import pytest

CONTRACT_FIXTURES_DIR = (
    Path(__file__).resolve().parent.parent / "fixtures" / "investigation" / "extraction_contract"
)

ALLOWED_CLAIM_KINDS = {
    "claimed_employer",
    "contact",
    "job_reference_id",
    "joining_date",
    "location",
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
    "absent",
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
        assert any(isinstance(ex.get(k), str) and ex[k] for k in ["raw_text", "ocr_text", "redacted_text"])

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
            assert claim.get("confidence_tier") in ALLOWED_CONFIDENCE_TIERS | {None}, (
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
                assert span["target_text"] in {"raw_text", "ocr_text", "redacted_text"}
                raw_text = ex[span["target_text"]]
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
            elif claim["extraction_status"] in {"absent", "user_corrected"}:
                assert quote is None
            elif quote is not None:
                assert any(quote in ex.get(buffer, "") for buffer in ["raw_text", "ocr_text", "redacted_text"])


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


def test_manifest_and_enum_consistency(all_contract_examples):
    index = json.loads((CONTRACT_FIXTURES_DIR / 'index.json').read_text(encoding="utf-8"))
    assert index['total_examples'] == len(all_contract_examples)
    assert len({ex['example_id'] for ex in all_contract_examples}) == len(all_contract_examples)
    assert {e['file'] for e in index['examples']} == {p.name for p in CONTRACT_FIXTURES_DIR.glob('example_*.json')}
    for entry in index['examples']:
        ex = json.loads((CONTRACT_FIXTURES_DIR / entry['file']).read_text(encoding="utf-8"))
        assert ex['example_id'] == entry['example_id']
        assert ex['contract_version'] == index['contract_version']
    document = Path(__file__).resolve().parents[3] / 'docs/extraction-requirements.md'
    kinds = document.read_text(encoding="utf-8").split('Kinds:', 1)[1].split('Absent fields', 1)[0]
    assert set(re.findall(r'`([a-z_]+)`', kinds)) == ALLOWED_CLAIM_KINDS


def test_compensation_semantics(all_contract_examples):
    for ex in all_contract_examples:
        for c in ex['extraction']['claims']:
            if c['kind'] != 'compensation':
                continue
            a = c['attributes']
            assert a['amount_unit'] == 'currency_base_unit'
            assert a['period'] in {None, 'ANNUAL', 'MONTHLY', 'HOURLY', 'DAILY', 'TOTAL'}
            assert a['pay_type'] in {'salary', 'stipend', 'bonus', 'accumulated_earnings', 'unknown'}
            if '7.2 LPA' in c['value']:
                assert a['amount'] == 720000 and a['period'] == 'ANNUAL'
            if c['value'] in {'INR 7,50,000', 'INR 15,000'}:
                assert a['period'] is None and c['extraction_status'] == 'ambiguous'
                assert any(u['claim_id'] == c['claim_id'] and u['field'] == 'period' for u in ex['extraction']['unresolved_ambiguities'])


def test_absence_unknown_roles_and_boundary(all_contract_examples):
    for ex in all_contract_examples:
        for c in ex['extraction']['claims']:
            assert not {'independent_footprint', 'canonical_domain', 'mca_status', 'entity_resolution_status'}.intersection(c['attributes'])
            if c['extraction_status'] == 'absent':
                assert all(c[k] is None for k in ['value', 'source_quote', 'source_span', 'confidence_tier'])
            else:
                assert c['value'] is not None and c['confidence_tier'] in ALLOWED_CONFIDENCE_TIERS
            if c['attributes'].get('semantic_role') == 'unknown':
                assert c['kind'] == 'contact' and c['extraction_status'] == 'ambiguous'


def test_correction_targets_and_ambiguity_references(all_contract_examples):
    from datetime import datetime
    for ex in all_contract_examples:
        claims = {c['claim_id']:c for c in ex['extraction']['claims']}
        for u in ex['extraction']['unresolved_ambiguities']:
            assert u['claim_id'] in claims
        for c in claims.values():
            assert re.fullmatch(r'CLM-\d{2,}-\d{2,}', c['claim_id'])
            if c['extraction_status'] == 'user_corrected':
                a = c['attributes'];target = a['target_claim_id']
                assert target in claims and target != c['claim_id']
                assert a['attribution']['target_claim_id'] == target
                assert a['corrected_field'] in claims[target]['attributes']
                assert c['value'] == a['corrected_value']
                assert datetime.fromisoformat(a['attribution']['timestamp'].replace('Z', '+00:00')).tzinfo


def test_modality_consistency(all_contract_examples):
    for ex in all_contract_examples:
        for c in ex['extraction']['claims']:
            if c['kind'] not in {'payment_request', 'credential_request'}:
                continue
            a = c['attributes'];m = a['modality']
            assert m in {'active_demand', 'negated_policy', 'quoted_advisory', 'hypothetical_or_conditional', 'ambiguous'}
            if m == 'active_demand':
                assert a['is_active_demand'] is True
            elif m in {'negated_policy', 'quoted_advisory'}:
                assert a['is_active_demand'] is False
            assert {'requested_action', 'actor', 'recipient'} <= a.keys()


def test_reserved_identifiers_and_sanitized_ocr(all_contract_examples):
    from urllib.parse import urlparse
    def reserved(host):
        return host in {'example.com', 'example.org', 'example.net'} or host.endswith(('.example', '.invalid', '.test'))
    for ex in all_contract_examples:
        text = json.dumps(ex)
        for host in re.findall(r'[\w.+-]+@([\w.-]+\.[A-Za-z]+)', text):
            assert reserved(host.rstrip('.'))
        for url in re.findall(r'https?://[^\s"<>]+', text):
            assert reserved(urlparse(url).hostname or '')
        for c in ex['extraction']['claims']:
            if c['source_span']:
                assert c['source_span'].get('page_number') is None
                assert c['source_span'].get('bounding_box') is None
    ocr = next(ex for ex in all_contract_examples if ex['extraction']['source_type'] == 'screenshot')
    assert all(c['source_span']['target_text'] == 'redacted_text' for c in ocr['extraction']['claims'])
