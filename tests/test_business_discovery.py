"""Contract candidates require source evidence and never become approved implicitly."""
import zipfile

from app.business_discovery import discover_business_candidates


def archive(tmp_path, files):
    path = tmp_path / "sample.zip"
    with zipfile.ZipFile(path, "w") as handle:
        for name, content in files.items():
            handle.writestr(name, content)
    return path


def test_readme_prioritizes_but_does_not_authorize(tmp_path):
    path = archive(tmp_path, {
        "repo/README.md": "See `app/workflow.py` for the approval workflow.",
        "repo/app/workflow.py": "def approve_request():\n    return False\n",
        "repo/app/incident.py": "class IncidentRecord:\n    pass\n",
    })
    result = discover_business_candidates(path)
    contracts = result["blueprint"]["business_contracts"]
    assert len(contracts) == 2
    assert contracts[0]["name"] == "approve_request"
    assert contracts[0]["kind"] == "approval_rule"
    assert all(item["status"] == "review" for item in contracts)
    assert all(item["evidence"][0]["source_file"].startswith("repo/app/") for item in contracts)
    assert result["blueprint"]["execution_enabled"] is False


def test_readme_claim_without_matching_source_symbol_is_not_contract(tmp_path):
    path = archive(tmp_path, {
        "README.md": "Approvals in `app/workflow.py`",
        "app/workflow.py": "def unrelated():\n    pass\n",
    })
    result = discover_business_candidates(path)
    assert result["candidate_count"] == 0
    assert len(result["readme_guidance"]["candidate_targets"]) == 1


def test_json_policy_keys_are_candidates_not_approved_rules(tmp_path):
    path = archive(tmp_path, {
        "data/policies.json": '{"approval_groups": ["IT"], "execution_policy": {"enabled": false}}',
    })
    result = discover_business_candidates(path)
    assert {item["kind"] for item in result["blueprint"]["business_contracts"]} == {
        "approval_rule", "execution_policy"
    }
    assert all(item["status"] == "review" for item in result["blueprint"]["business_contracts"])


def test_no_readme_still_scans_source(tmp_path):
    path = archive(tmp_path, {"app/incident.py": "class Incident:\n    pass\n"})
    assert discover_business_candidates(path)["candidate_count"] == 1

