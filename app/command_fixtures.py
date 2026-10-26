"""Representative read-only command fixtures and conservative demo parsers.

No subprocess, shell, SSH, Ansible or network transport exists in this module.
These parsers cover the committed fixture layouts, not arbitrary vendor releases.
"""

from copy import deepcopy
from datetime import datetime, timezone
from ipaddress import IPv4Address, IPv4Interface
import json
from pathlib import Path
import re

from .seeded_network_import import digest as contract_digest

FIXTURES = json.loads(
    (
        Path(__file__).resolve().parents[1] / "data/network_command_fixtures.json"
    ).read_text(encoding="utf-8")
)
PROFILE_DIGEST = contract_digest(FIXTURES)
COMMANDS = FIXTURES["commands"]
SIGNALS = {
    "bfd": "bfd.session_down",
    "inventory": "hardware.card_missing",
    "management": "management.switch_down_investigation",
}


def command_definitions():
    return [
        {
            "command_id": key,
            **{name: value[name] for name in ("command", "platform", "context")},
            "simulation_only": True,
            "profile": FIXTURES["profile"],
        }
        for key, value in COMMANDS.items()
    ]


def simulate_command(row, command_id, peer_ip):
    if command_id not in COMMANDS:
        raise ValueError("Unsupported simulated command")
    definition = COMMANDS[command_id]
    reachable = row["sample"]["management_reachable"]
    result = {
        **{key: definition[key] for key in ("command", "platform", "context")},
        "command_id": command_id,
        "profile": FIXTURES["profile"],
        "simulation_only": True,
        "device_id": row["device_id"],
        "source_cycle": row["cycle"],
        "source_episode": row["episode"],
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "stdout": "",
        "stderr": "",
        "exit_code": None,
    }
    if reachable is not True:
        result.update(
            transport_status="timeout" if reachable is False else "collector_error",
            stderr="[SIMULATED] Management connection timed out; power state unknown."
            if reachable is False
            else "[SIMULATED] Collector returned no observation; node state unknown.",
        )
        return result
    if command_id == "bfd_sessions":
        key = {"up": "up", "down": "down"}.get(row["sample"]["bfd_state"])
    elif command_id == "card_inventory":
        missing = row["sample"]["card_missing"]
        key = (
            "missing" if missing is True else ("present" if missing is False else None)
        )
    else:
        key = "addresses"
    result.update(transport_status="ok", exit_code=0)
    if key is None:
        result.update(
            exit_code=1, stderr="[SIMULATED] Requested observation is unavailable."
        )
    else:
        result["stdout"] = definition["outputs"][key].format(
            peer_ip=str(IPv4Address(peer_ip)),
            management_ip=str(IPv4Address(row["management_ip"])),
        )
    return result


def parse_bfd(text):
    if not all(
        header in text
        for header in (
            "BFD Session",
            "Tx Intvl",
            "Rx Intvl",
            "Multipl",
        )
    ):
        raise ValueError("Unrecognised BFD fixture header or session count")
    if not re.search(r"^No\. of BFD sessions: 1\s*$", text, re.MULTILINE):
        raise ValueError("Expected a one-session fixture footer")
    rows = re.findall(
        r"^lab-peer\s+(Up|Down|Init|AdminDown)\s+\(([0-3])\)\s+(\d+)\s+(\d+)\s+(\d+)\s*$",
        text,
        re.MULTILINE,
    )
    peers = re.findall(r"^\s+([0-9.]+)\s+(bgp|ospf|isis)\s*$", text, re.MULTILINE)
    if len(rows) != 1 or len(peers) != 1:
        raise ValueError("Expected one complete BFD fixture session")
    state, code, tx, rx, multiplier = rows[0]
    if {"AdminDown": "0", "Down": "1", "Init": "2", "Up": "3"}[state] != code:
        raise ValueError("Contradictory BFD state code")
    if not all(0 < int(value) <= 100000 for value in (tx, rx, multiplier)):
        raise ValueError("Invalid BFD timer data")
    return {
        "session_state": state.lower(),
        "peer_ip": str(IPv4Address(peers[0][0])),
        "protocol": peers[0][1],
        "tx_interval_ms": int(tx),
        "rx_interval_ms": int(rx),
        "multiplier": int(multiplier),
    }


def parse_card(text):
    names = (
        "Slot",
        "Provisioned Card-type",
        "Equipped Card-type",
        "Admin State",
        "Operational State",
    )
    lines = text.splitlines()
    headers = [line for line in lines if all(name in line for name in names)]
    if len(headers) != 1 or "Card Summary" not in lines:
        raise ValueError("Unrecognised card fixture header")
    starts = [headers[0].index(name) for name in names]
    if starts != sorted(starts):
        raise ValueError("Unrecognised card column order")
    rows = [line for line in lines if re.match(r"^1\s", line)]
    if len(rows) != 1:
        raise ValueError("Expected slot 1 in the card fixture")
    values = [
        rows[0][start:end].strip()
        for start, end in zip(starts, starts[1:] + [len(rows[0])])
    ]
    slot, provisioned, equipped, admin, operational = values
    if (
        slot != "1"
        or not provisioned
        or admin not in {"up", "down"}
        or operational not in {"up", "provisioned", "down"}
    ):
        raise ValueError("Incomplete card fixture observation")
    missing = (
        True
        if not equipped and admin == "up" and operational == "provisioned"
        else False
        if equipped == provisioned and admin == "up" and operational == "up"
        else None
    )
    return {
        "slot": slot,
        "provisioned_type": provisioned,
        "equipped_type": equipped or None,
        "admin_state": admin,
        "operational_state": operational,
        "card_missing": missing,
    }


def parse_addresses(text):
    interface = re.search(
        r"^2: eth0: <([^>]+)>.*\bstate (UP|DOWN|UNKNOWN)\s*$", text, re.MULTILINE
    )
    addresses = re.findall(
        r"^\s+inet ([0-9./]+) scope global eth0\s*$", text, re.MULTILINE
    )
    if not interface or len(addresses) != 1:
        raise ValueError("Expected a complete eth0 address fixture")
    address = IPv4Interface(addresses[0])
    return {
        "interface": "eth0",
        "flags": interface[1].split(","),
        "state": interface[2],
        "address": str(address),
        "ipv4": str(address.ip),
    }


def parse_result(run):
    definition = COMMANDS.get(run.get("command_id"))
    if (
        not definition
        or any(
            run.get(key) != definition[key]
            for key in ("command", "platform", "context")
        )
        or run.get("profile") != FIXTURES["profile"]
    ):
        return {
            "status": "unknown",
            "fields": {},
            "reason": "Unsupported command profile",
        }
    if run.get("transport_status") != "ok" or run.get("exit_code") != 0:
        return {
            "status": "unknown",
            "fields": {},
            "reason": "No successful command output; inspect transport/collector evidence",
        }
    text = run.get("stdout")
    if not isinstance(text, str) or len(text) > 20000:
        return {
            "status": "unknown",
            "fields": {},
            "reason": "Missing or oversized output",
        }
    try:
        parser = {
            "bfd_sessions": parse_bfd,
            "card_inventory": parse_card,
            "linux_addresses": parse_addresses,
        }[run["command_id"]]
        return {
            "status": "parsed",
            "fields": parser(text),
            "reason": "Parsed committed representative fixture layout",
        }
    except ValueError:
        return {
            "status": "unknown",
            "fields": {},
            "reason": "Output did not match the supported fixture layout",
        }


def command_evidence(monitor_evidence, runs):
    """Derive the three primary alarm signals from output/transport, not alarm flags."""
    evidence = deepcopy(monitor_evidence)
    row = evidence["latest"]
    latest = {}
    for run in runs:
        if (run["device_id"], run["source_cycle"], run["source_episode"]) != (
            row["device_id"],
            row["cycle"],
            row["episode"],
        ):
            raise ValueError("Command output belongs to different node evidence")
        latest[run["command_id"]] = run
    parsed = {key: parse_result(run) for key, run in latest.items()}
    node_runs = [
        run for key, run in latest.items() if key in ("bfd_sessions", "card_inventory")
    ]
    successful = any(run["transport_status"] == "ok" for run in node_runs)
    timed_out = bool(node_runs) and all(
        run["transport_status"] == "timeout" for run in node_runs
    )
    management = (
        True
        if successful and not any(run["transport_status"] != "ok" for run in node_runs)
        else False
        if timed_out
        else None
    )
    fields = {key: value["fields"] for key, value in parsed.items()}
    bfd = fields.get("bfd_sessions", {}).get("session_state")
    bfd_down = True if bfd == "down" else False if bfd == "up" else None
    missing = fields.get("card_inventory", {}).get("card_missing")
    alarms = {
        key: value
        for key, value in row["sample"].get("alarm_observations", {}).items()
        if key not in SIGNALS.values()
    }
    alarms.update(
        {
            SIGNALS["bfd"]: bfd_down,
            SIGNALS["inventory"]: missing,
            SIGNALS["management"]: None if management is None else not management,
        }
    )
    checks = []

    def add(name, observed, healthy, basis):
        status = "unknown" if observed is None else ("passed" if healthy else "failed")
        checks.append(
            {
                "check": name,
                "observed": observed,
                "status": status,
                "log": f"[SIMULATED COMMAND] {name}: {json.dumps(observed)}; result={status}; basis={basis}",
            }
        )

    add(
        "management",
        management,
        management is True,
        "Nokia fixture transport result; no inference about power",
    )
    add("bfd", bfd, bfd == "up", "show router bfd session output")
    if bfd not in (None, "up", "down"):
        checks[-1]["status"] = "unknown"
    add(
        "inventory",
        missing,
        missing is False,
        "show card slot 1 output; administratively disabled slots remain unknown",
    )
    linux = fields.get("linux_addresses", {})
    if "linux_addresses" in latest:
        expected = linux.get("ipv4") == row["management_ip"] if linux else None
        add(
            "linux_addresses",
            expected,
            expected is True,
            "Linux diagnostic fixture address; not BFD evidence",
        )
    for signal, value in alarms.items():
        if signal not in SIGNALS.values():
            add(
                signal,
                value,
                value is False,
                "injected synthetic alarm flag; no command parser",
            )
    row["sample"]["alarm_observations"] = alarms
    row["sample"]["management_reachable"] = management
    row["sample"]["bfd_state"] = bfd
    row["sample"]["card_missing"] = missing
    row["checks"] = checks
    row["status"] = (
        "attention"
        if any(check["status"] == "failed" for check in checks)
        else "unknown"
        if any(check["status"] == "unknown" for check in checks)
        else "healthy"
    )
    evidence.update(
        command_results=deepcopy(runs),
        parsed_commands=parsed,
        discovery_basis="command_outputs_for_primary_cases; injected_flags_for_other_scenarios",
    )
    return evidence

