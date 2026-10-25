"""Explainable catalog matching for advisory plans; scores are not probabilities."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter

METHOD = "catalog_terms_v1"
STOP_WORDS = frozenset(
    "a an and are as at be before by can confirm for from has have if in into is it of on or only run service services step steps that the their then this to using validate validation verify with without approved approval uat production application affected required previous after according review known good".split()
)


def _normal(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _terms(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]+", text.casefold())
        if len(word) > 2 and word not in STOP_WORDS
    }


def recommend_from_catalog(spec: dict, payload: dict) -> dict:
    """Require a clear textual match within the stated service or wildcard scope.

    Never choose the first catalog item on a tie. This local heuristic does not
    reproduce the original classifier, query memory or authorize any action.
    """
    service = _normal(payload.get("service"))
    incident_terms = _terms(
        " ".join(
            payload.get(key) or ""
            for key in (
                "short_description",
                "description",
                "customer_impact",
            )
        )
    )
    documents = []
    for dip in spec["dips"]:
        headline = _terms(" ".join(dip.get(key) or "" for key in ("title", "category")))
        body = _terms(
            " ".join(
                dip.get("implementation_steps", []) + dip.get("validation_steps", [])
            )
        )
        documents.append((dip, headline, body))
    frequency = Counter(
        term for _, headline, body in documents for term in headline | body
    )
    candidates = []
    for dip, headline, body in documents:
        scope = _normal(dip.get("service"))
        if not service or scope not in {service, "*"}:
            continue
        matched = incident_terms & (headline | body)
        distinctive = {
            term for term in matched if frequency[term] <= max(1, len(documents) // 2)
        }
        score = sum(3 if term in headline else 1 for term in matched) + (
            2 if scope == service else 0
        )
        reasons = [
            "Exact service match"
            if scope == service
            else "DIP explicitly supports any service"
        ]
        if matched:
            reasons.append("Source catalog terms: " + ", ".join(sorted(matched)))
        strong = len(distinctive) >= 2 and score >= 5
        candidates.append(
            {
                "dip_id": dip["dip_id"],
                "title": dip.get("title"),
                "service": dip.get("service"),
                "score": score,
                "matched_terms": sorted(matched),
                "reasons": reasons,
                "sufficient_evidence": strong,
                "required_approval_groups": dip.get("approval_groups", []),
            }
        )
    candidates.sort(key=lambda item: (-item["score"], item["dip_id"]))
    strong = [item for item in candidates if item["sufficient_evidence"]]
    status, selected = "no_match", None
    reason = "Enter a service and descriptive symptoms; no sufficiently supported DIP was found."
    if strong:
        top = candidates[0]
        runner_up = candidates[1]["score"] if len(candidates) > 1 else 0
        if (
            top["sufficient_evidence"]
            and top["score"] - runner_up >= 3
            and top["score"] >= runner_up * 1.25
        ):
            status, selected = "recommended", top["dip_id"]
            reason = "One catalog match has sufficient terms and a clear lead; review its advisory plan."
        else:
            status = "ambiguous"
            reason = "Several DIPs have similar support. Add specific symptoms or explicitly select a DIP for review."
    digest_input = {
        "payload": payload,
        "catalog": spec["dips"],
        "source_evidence": spec["source_evidence"],
        "method": METHOD,
    }
    digest = hashlib.sha256(
        json.dumps(digest_input, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "status": status,
        "recommended_dip_id": selected,
        "reason": reason,
        "method": METHOD,
        "candidates": candidates[:10],
        "evidence_digest": digest,
        "approval_evidence_trusted": False,
        "external_execution_enabled": False,
    }

