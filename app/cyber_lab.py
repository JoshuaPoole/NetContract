"""Deterministic cyber task previews. No command runner or network transport."""

import re

# Only these explicit interpretations are supported. Source prose is never shell code.
RULES = (
    (r"^(confirm|scope|assess|triage)\b", "inspect_context", ["hostnamectl"]),
    (
        r"^(preserve|collect|capture|record|document)\b",
        "preserve_evidence",
        ["journalctl", "--no-pager", "-n", "50"],
    ),
    (
        r"^(contain|isolate|restrict|block|disable)\b",
        "isolate_fixture",
        ["netcontract-lab", "isolate"],
    ),
    (
        r"^(identify|inspect|investigate|review|determine|check)\b",
        "inspect_services",
        ["ss", "-lntp"],
    ),
    (
        r"^(apply|patch|remediate|remove|restore|rebuild|recover|eradicate)\b",
        "repair_fixture",
        ["netcontract-lab", "repair"],
    ),
    (
        r"^(rotate|revoke|reset)\b",
        "rotate_fixture_credentials",
        ["netcontract-lab", "rotate-placeholder"],
    ),
    (
        r"^(monitor|validate|verify|test|watch)\b",
        "observe_fixture",
        ["netcontract-lab", "status"],
    ),
)


def plan(steps):
    tasks = []
    for index, step in enumerate(steps, 1):
        rule = next(
            (
                item
                for item in RULES
                if isinstance(step, str) and re.search(item[0], step.strip(), re.I)
            ),
            None,
        )
        tasks.append(
            {
                "step_number": index,
                "source_step": step,
                "adapter": rule[1] if rule else None,
                "module": "ansible.builtin.command" if rule else None,
                "argv_preview": list(rule[2]) if rule else [],
                "supported": rule is not None,
                "simulation_only": True,
                "interpretation": "Bounded verb adapter; engineer must review. Not a complete executable translation."
                if rule
                else "Manual review: no supported adapter.",
            }
        )
    return tasks


def collect(node, environment, inventory, state, version):
    active = state != "up"
    signal = inventory["cyber"]["signal"]
    output = f"fixture_profile=cyber-v1 node={node} environment={environment} signal={signal} active={str(active).lower()} version={version}"
    return {
        "simulation_only": True,
        "controller": "localhost",
        "node": node,
        "environment": environment,
        "target_ip": inventory["management_ip"],
        "credential_profile": "demo-placeholder-not-used",
        "network_io": False,
        "real_execution_enabled": False,
        "observation_state": "active" if active else "clear",
        "alarms": [
            {
                "signal": signal,
                "node": node,
                "environment": environment,
                "basis": "explicit synthetic cyber fixture",
            }
        ]
        if active
        else [],
        "command_runs": [
            {
                "command": "journalctl --no-pager -n 50",
                "stdout": output,
                "exit_code": 0,
                "simulation_only": True,
            }
        ],
        "ansible_style_log": f"PLAY [{environment.upper()} | CYBER FIXTURE | SIMULATION ONLY]\nTASK [Simulated login via localhost]\nok: [{node}] target={inventory['management_ip']}; placeholder credentials unused; authentication not attempted\nTASK [Fixture: journalctl --no-pager -n 50]\nok: [{node}] => {output}\nPLAY RECAP real network calls=0; Ansible process started=false",
    }


def simulate_tasks(tasks, node):
    return "\n".join(
        f"TASK [{task['step_number']}: {task['adapter']}]\nchanged: [{node}] => SIMULATED adapter result only; argv preview={task['argv_preview']!r}; command was not executed"
        for task in tasks
    )
