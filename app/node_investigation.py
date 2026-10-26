"""Environment-bound BFD fixture investigations over published Salesforce steps.

No SSH, sockets, shell, Ansible subprocesses or real credentials are used.
"""

from copy import deepcopy
import json
from pathlib import Path
import re
import secrets
from threading import RLock
import time
import uuid

from fastapi import HTTPException

from .command_fixtures import simulate_command, parse_result, PROFILE_DIGEST
from .seeded_network_import import digest
from . import cyber_lab

REGISTRY = json.loads(
    (Path(__file__).resolve().parents[1] / "data/node_lab.json").read_text()
)
LOCK = RLock()
SESSIONS = {}
STATE = {}
NUMBERS = {
    word: str(index)
    for index, word in enumerate(
        (
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
        )
    )
}


def parse_target(message):
    found = re.findall(
        r"\bnode[\s-]*(\d{1,5}|one|two|three|four|five|six|seven|eight|nine|ten)\b",
        message,
        re.I,
    )
    nodes = {"NODE-" + NUMBERS.get(value.lower(), value).zfill(5) for value in found}
    if len(nodes) != 1 or re.search(
        r"\bnodes?\s*\d+\s*(?:and|,)\s*(?:node\s*)?\d+", message, re.I
    ):
        raise ValueError(
            "Name one node, for example: list BFD alarms on node 3 in UAT."
        )
    node = nodes.pop()
    if node not in REGISTRY["nodes"]:
        raise ValueError(
            "That node is not in the configured synthetic lab inventory (nodes 1–8)."
        )
    aliases = {
        "uat": "uat",
        "prod": "production",
        "production": "production",
        "dev": "development",
        "development": "development",
        "test": "test",
        "staging": "staging",
        "stage": "staging",
        "qa": "qa",
        "sandbox": "sandbox",
        "lab": "uat",
    }
    environments = {
        aliases[word.lower()]
        for word in re.findall(
            r"\b(uat|prod|production|dev|development|test|staging|stage|qa|sandbox|lab)\b",
            message,
            re.I,
        )
    }
    for label in re.findall(
        r"\b(?:in|environment|env)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9_-]*)", message, re.I
    ):
        if label.lower() not in aliases and label.lower() not in {"node", "nodes"}:
            raise ValueError(
                "Unknown requested environment; the demo node registry must explicitly define it."
            )
    configured = REGISTRY["nodes"][node]["environment"]
    if len(environments) > 1 or (environments and configured not in environments):
        raise ValueError(
            f"{node} is configured for synthetic {configured.upper()}, not the requested environment. No cross-environment fallback is allowed."
        )
    return node, configured, bool(environments)


def procedures(config, query):
    rows = query(
        f"SELECT Id, Name, LastModifiedDate, {', '.join(sorted(config['fields']))} FROM {config['object']} LIMIT 1001"
    )
    if len(rows) > 1000:
        raise ValueError("Published procedure catalog exceeds the bounded window")
    allowed = set(config["allowed_ids"])
    return [
        {
            "record_id": row["Id"],
            "procedure_id": row[config["identity"]],
            "last_modified": row.get("LastModifiedDate"),
            "values": {
                source: row.get(target) for target, source in config["fields"].items()
            },
        }
        for row in rows
        if row.get(config["identity"]) in allowed
    ]


def decoded(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def collect(node, environment, state, version, scenario="bfd"):
    if scenario == "cyber":
        return cyber_lab.collect(
            node, environment, REGISTRY["nodes"][node], state, version
        )
    inventory = REGISTRY["nodes"][node]
    row = {
        "device_id": node,
        "management_ip": inventory["management_ip"],
        "cycle": version,
        "episode": version,
        "sample": {
            "management_reachable": True,
            "bfd_state": state,
            "card_missing": False,
        },
    }
    runs = [
        simulate_command(row, command, inventory["peer_ip"])
        for command in ("bfd_sessions", "linux_addresses")
    ]
    parsed = {run["command_id"]: parse_result(run) for run in runs}
    bfd = parsed["bfd_sessions"]["fields"]
    observed = bfd.get("session_state")
    alarms = (
        [
            {
                "signal": "bfd.session_down",
                "node": node,
                "environment": environment,
                "observed_at": runs[0]["observed_at"],
                "peer_ip": bfd.get("peer_ip"),
                "basis": "parsed show router bfd session fixture",
            }
        ]
        if observed == "down"
        else []
    )
    trace = [
        f"PLAY [{environment.upper()} | BFD diagnostics | SIMULATION ONLY]",
        f"TASK [Simulated login via {REGISTRY['controller']}]",
        f"ok: [{node}] target={inventory['management_ip']} credentials={REGISTRY['credential_profile']}; authentication not attempted",
    ]
    for run in runs:
        trace += [
            f"TASK [Fixture: {run['command']}]",
            f"ok: [{node}] => exit_code={run['exit_code']}",
            run["stdout"] or run["stderr"],
        ]
    trace.append(
        f"PLAY RECAP [{node}] simulated tasks={len(runs) + 1}; real network calls=0; Ansible process started=false"
    )
    return {
        "simulation_only": True,
        "controller": "localhost",
        "node": node,
        "environment": environment,
        "target_ip": inventory["management_ip"],
        "credential_profile": REGISTRY["credential_profile"],
        "registry_digest": digest(REGISTRY),
        "command_profile_digest": PROFILE_DIGEST,
        "command_runs": runs,
        "parsed_commands": parsed,
        "alarms": alarms,
        "bfd_state": observed,
        "ansible_style_log": "\n".join(trace),
        "network_io": False,
        "real_execution_enabled": False,
    }


def public(session):
    return {
        key: deepcopy(value)
        for key, value in session.items()
        if key not in {"expires", "confirmation", "confirmation_expires"}
    }


def investigate(project, config, message, query):
    node, environment, explicit_environment = parse_target(message)
    scenario = (
        "cyber"
        if re.search(
            r"\b(cyber|malware|exfiltration|exploit(?:ation)?|compromise|breach|ransomware)\b",
            message,
            re.I,
        )
        else "bfd"
    )
    if scenario == "cyber" and re.search(r"\bbfd\b", message, re.I):
        raise ValueError("Choose one incident context: BFD or a cyber scenario.")
    if scenario == "bfd" and not re.search(r"\bbfd\b", message, re.I):
        raise ValueError(
            "Name the reported BFD or supported cyber symptoms for this node; a target alone does not establish the incident type."
        )
    inventory = REGISTRY["nodes"][node]
    if scenario == "cyber":
        profile = inventory.get("cyber")
        if not profile:
            raise ValueError(
                "No cyber fixture is configured for this node. Use node 4 for application exploitation, 5 for endpoint compromise, or 6 for exfiltration."
            )
        requested = set()
        for kind, pattern in (
            ("application", r"\b(application|server|exploit|exploitation)\b"),
            ("endpoint", r"\b(endpoint|malware|ransomware)\b"),
            ("exfiltration", r"\b(exfiltration|breach)\b"),
        ):
            if re.search(pattern, message, re.I):
                requested.add(kind)
        if requested and requested != {profile["kind"]}:
            raise ValueError(
                "Reported cyber symptoms do not match this node's configured synthetic scenario. Clarify the target; no fallback was used."
            )
    with LOCK:
        for key in list(SESSIONS):
            if SESSIONS[key]["expires"] < time.monotonic():
                del SESSIONS[key]
        if len(SESSIONS) >= 200:
            raise ValueError(
                "Too many pending investigations; wait for old sessions to expire"
            )
        key = (project, node, environment, scenario)
        state, version = STATE.get(
            key, ("active" if scenario == "cyber" else inventory["bfd_state"], 1)
        )
        evidence = collect(node, environment, state, version, scenario)
        identifier = (
            inventory["cyber"]["procedure_id"]
            if scenario == "cyber"
            else inventory["procedure_id"]
        )
        matches = [
            row
            for row in procedures(config, query)
            if row["procedure_id"] == identifier
        ]
        procedure = matches[0] if len(matches) == 1 and evidence["alarms"] else None
        blockers = []
        steps = (
            decoded(procedure["values"].get("implementation_steps"))
            if procedure
            else None
        )
        if not evidence["alarms"]:
            blockers.append(
                "No matching active alarm was observed in this fixture; recovery approval is unavailable."
            )
        if not procedure:
            blockers.append(
                "No unique published Salesforce procedure matches this lab node binding."
            )
        if not isinstance(steps, list) or not steps:
            blockers.append(
                "Approve, sync and publish implementation_steps before requesting review."
            )
        task_plan = (
            cyber_lab.plan(steps)
            if scenario == "cyber" and isinstance(steps, list)
            else []
        )
        if any(not task["supported"] for task in task_plan):
            blockers.append(
                "Some procedure steps have no supported synthetic adapter; engineer review is required before this simulation can proceed."
            )
        target_environments = (
            decoded(procedure["values"].get("target_environment_order"))
            if procedure
            else None
        )
        if target_environments is not None and (
            not isinstance(target_environments, list)
            or environment not in target_environments
        ):
            blockers.append(
                "The published procedure does not include this node environment."
            )
        session = {
            "session_id": uuid.uuid4().hex,
            "project_id": project,
            "node": node,
            "scenario": scenario,
            "task_plan": task_plan,
            "task_log": None,
            "environment": environment,
            "environment_basis": "speaker + lab registry"
            if explicit_environment
            else "configured lab registry",
            "publication_digest": config["publication_digest"],
            "version": version,
            "phase": "awaiting_review" if not blockers else "review_blocked",
            "procedure": procedure,
            "procedure_digest": digest(procedure),
            "prechecks": evidence,
            "postchecks": None,
            "proposed_steps": steps if isinstance(steps, list) else [],
            "blockers": blockers,
            "procedure_environment_published": target_environments is not None,
            "environment_note": "Node environment is bound by the explicit synthetic lab registry; absent Salesforce environment metadata is not inferred from speech.",
            "simulation_only": True,
            "execution_enabled": False,
            "authorization_evidence_trusted": False,
            "expires": time.monotonic() + 300,
        }
        session["evidence_digest"] = digest(
            {
                key: session[key]
                for key in (
                    "node",
                    "environment",
                    "version",
                    "publication_digest",
                    "procedure_digest",
                    "prechecks",
                )
            }
        )
        SESSIONS[session["session_id"]] = session
        return public(session)


def review(
    project, config, session_id, version, evidence_digest, query, confirmation=None
):
    with LOCK:
        session = SESSIONS.get(session_id)
        if (
            not session
            or session["project_id"] != project
            or session["expires"] < time.monotonic()
        ):
            raise HTTPException(
                409,
                "Investigation expired or belongs to another workspace; investigate again",
            )
        key = (project, session["node"], session["environment"], session["scenario"])
        current_version = STATE.get(
            key, (REGISTRY["nodes"][session["node"]]["bfd_state"], 1)
        )[1]
        if (
            session["version"] != version
            or current_version != version
            or session["evidence_digest"] != evidence_digest
            or session["publication_digest"] != config["publication_digest"]
        ):
            raise HTTPException(
                409,
                "Node evidence or published configuration changed; investigate again",
            )
        matches = (
            [
                row
                for row in procedures(config, query)
                if row["procedure_id"] == session["procedure"]["procedure_id"]
            ]
            if session["procedure"]
            else []
        )
        if len(matches) != 1 or digest(matches[0]) != session["procedure_digest"]:
            raise HTTPException(
                409,
                "Salesforce procedure changed; investigate and review its current steps again",
            )
        if confirmation is None:
            if session["phase"] != "awaiting_review" or session["blockers"]:
                raise HTTPException(
                    409, "This investigation is not awaiting an eligible review"
                )
            session["confirmation"] = secrets.token_hex(16)
            session["confirmation_expires"] = time.monotonic() + 90
            session["phase"] = "awaiting_confirmation"
            return {
                "session": public(session),
                "confirmation_id": session["confirmation"],
                "reply": f"Confirm the simulated intervention for {session['node']} in {session['environment'].upper()}. This changes only the in-memory fixture state, then reruns postchecks. It does not execute the procedure on a device.",
            }
        if (
            session["phase"] != "awaiting_confirmation"
            or session.get("confirmation_expires", 0) < time.monotonic()
            or not secrets.compare_digest(session.get("confirmation", ""), confirmation)
        ):
            raise HTTPException(
                409, "Confirmation expired, consumed or invalid; investigate again"
            )
        session.pop("confirmation", None)
        STATE[key] = ("up", version + 1)
        session["postchecks"] = collect(
            session["node"],
            session["environment"],
            "up",
            version + 1,
            session["scenario"],
        )
        session["task_log"] = (
            cyber_lab.simulate_tasks(session["task_plan"], session["node"])
            if session["scenario"] == "cyber"
            else None
        )
        session["phase"] = (
            "simulated_recovery_verified"
            if not session["postchecks"]["alarms"]
            else "postcheck_failed"
        )
        return {
            "session": public(session),
            "reply": f"Postchecks show simulated recovery on {session['node']} in {session['environment'].upper()}. The lab injected a healthy state; no real login, command or remediation occurred.",
        }
