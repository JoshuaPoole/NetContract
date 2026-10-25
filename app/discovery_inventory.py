"""Focused business-contract and infrastructure discovery for LifeAfterCode."""
from pathlib import Path

from .business_discovery import discover_business_candidates
from .discovery import _read_entries
from .terraform_inventory import discover_terraform
from .seeded_network_import import discover_entries


def build_discovery_inventory(archive: Path) -> dict:
    """Keep business behavior and declared infrastructure as separate inventories."""
    business = discover_business_candidates(archive)
    entries = list(_read_entries(archive))
    seeds = discover_entries(entries, 'review-required-lab-namespace')
    return {
        "business_contracts": business["blueprint"]["business_contracts"],
        "business_warnings": business["warnings"],
        "terraform": discover_terraform(entries),
        "seeded_network": seeds,
        "static_only": True,
    }
