import json
import re
from pathlib import Path
import pytest
from backend.tests.investigation.conftest import load_all_fixtures, FIXTURES_DIR

REQUIRED_CASE_CATEGORIES = {
    "lookalike_domain",
    "unknown_recruiter_unresolved_domain",
    "phone_only_recruiter",
    "negated_fee_policy",
    "quoted_scam_warning",
    "benign_telegram_mention",
    "upfront_fee_demand",
    "credential_otp_theft",
    "payment_to_unlock_earnings",
    "sparse_footprint_startup",
    "empty_search_results",
    "provider_failure_or_rate_limit",
    "realistic_impersonation",
    "agency_recruitment",
    "contact_role_separation",
    "company_extraction_platform_trap",
}

REQUIRED_KEYS = [
    "case_id",
    "category",
    "title",
    "description",
    "synthetic",
    "unresolved_facts",
    "labels",
    "raw_text",
    "structured_input",
    "provider_status",
    "search_mock",
    "expected_observations",
    "rationale",
]

STRUCTURED_INPUT_KEYS = [
    "company_name",
    "recruiter_email",
    "recruiter_phone",
    "demanded_fee",
    "payment_method",
    "flags",
]


def test_fixture_corpus_count(all_investigation_fixtures):
    """Corpus must contain at least 16 reproducible scenarios."""
    assert len(all_investigation_fixtures) >= 16, f"Expected at least 16 fixtures, found {len(all_investigation_fixtures)}"


def test_fixture_case_ids_unique(all_investigation_fixtures):
    """Every fixture must have a globally unique, stable case_id."""
    case_ids = [f.get("case_id") for f in all_investigation_fixtures]
    assert len(case_ids) == len(set(case_ids)), f"Duplicate case IDs found: {case_ids}"
    for cid in case_ids:
        assert isinstance(cid, str) and cid.startswith("CASE-"), f"Invalid case_id format: {cid}"


def test_fixture_required_structure(all_investigation_fixtures):
    """Every fixture must adhere to the agreed local schema."""
    for fixture in all_investigation_fixtures:
        cid = fixture.get("case_id")
        for key in REQUIRED_KEYS:
            assert key in fixture, f"Missing required key '{key}' in fixture {cid}"

        assert fixture["synthetic"] is True, f"Fixture {cid} must be labeled synthetic=True"
        assert isinstance(fixture["unresolved_facts"], list), f"unresolved_facts must be list in {cid}"
        assert isinstance(fixture["labels"], dict), f"labels must be dict in {cid}"
        assert "threat_category" in fixture["labels"], f"labels.threat_category missing in {cid}"
        assert "expected_verdict" in fixture["labels"], f"labels.expected_verdict missing in {cid}"

        # Structured input validation
        struct_in = fixture["structured_input"]
        assert isinstance(struct_in, dict), f"structured_input must be dict in {cid}"
        for in_key in STRUCTURED_INPUT_KEYS:
            assert in_key in struct_in, f"Missing structured_input key '{in_key}' in {cid}"

        # Provider status validation
        assert fixture["provider_status"] in ("successful", "empty", "failed"), (
            f"Invalid provider_status '{fixture['provider_status']}' in {cid}"
        )

        # Search mock validation
        search_mock = fixture["search_mock"]
        assert isinstance(search_mock, dict), f"search_mock must be dict in {cid}"
        assert "query_responses" in search_mock, f"search_mock.query_responses missing in {cid}"
        assert "default_response" in search_mock, f"search_mock.default_response missing in {cid}"

        # Expected observations validation
        exp_obs = fixture["expected_observations"]
        assert isinstance(exp_obs, dict), f"expected_observations must be dict in {cid}"
        assert "overall_outcome" in exp_obs, f"overall_outcome missing in {cid}"
        assert "authenticity_status" in exp_obs, f"authenticity_status missing in {cid}"
        assert exp_obs["authenticity_status"] == "UNCONFIRMED", (
            f"authenticity_status in {cid} must remain UNCONFIRMED without official employer confirmation"
        )

        # Rationale non-empty
        assert isinstance(fixture["rationale"], str) and len(fixture["rationale"].strip()) > 10, (
            f"rationale in {cid} must be informative string"
        )


def test_coverage_of_required_scenarios(all_investigation_fixtures):
    """Verify that all 16 required investigation scenarios are represented in the corpus."""
    covered_categories = {f.get("category") for f in all_investigation_fixtures}
    missing = REQUIRED_CASE_CATEGORIES - covered_categories
    assert not missing, f"Missing required scenario categories: {missing}"


def test_safety_and_synthetic_isolation(all_investigation_fixtures):
    """Ensure no real credentials, private personal records, or live API keys exist in fixtures."""
    forbidden_patterns = [r"AIzaSy[A-Za-z0-9_-]{33}", r"ghp_[A-Za-z0-9]{36}", r"sk-[a-zA-Z0-9_-]{20,}", r"Bearer\s+[A-Za-z0-9._-]{20,}"]
    for fixture in all_investigation_fixtures:
        content_str = json.dumps(fixture)
        for pattern in forbidden_patterns:
            assert not re.search(pattern, content_str), f"Forbidden credential pattern '{pattern}' matched in {fixture.get('case_id')}"

        # Ensure domains used in synthetic email/links are either reserved example domains or public real portals
        recruiter_email = fixture["structured_input"].get("recruiter_email")
        if recruiter_email and "@" in recruiter_email:
            domain = recruiter_email.split("@")[-1].lower()
            allowed_top_levels = [".example", ".com", ".org", ".in", ".net"]
            assert any(domain.endswith(tld) for tld in allowed_top_levels), (
                f"Email domain '{domain}' in {fixture.get('case_id')} has unexpected TLD"
            )


def test_index_manifest_matches_files():
    """Verify index.json accurately reflects the files present in the fixture directory."""
    index_file = FIXTURES_DIR / "index.json"
    assert index_file.exists(), "index.json must exist in fixtures directory"

    with open(index_file, "r", encoding="utf-8") as f:
        index_data = json.load(f)

    assert "cases" in index_data
    assert len(index_data["cases"]) >= 16

    for case_meta in index_data["cases"]:
        file_path = FIXTURES_DIR / case_meta["file"]
        assert file_path.exists(), f"File {case_meta['file']} referenced in index.json does not exist"
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data["case_id"] == case_meta["case_id"]
            assert data["category"] == case_meta["category"]
