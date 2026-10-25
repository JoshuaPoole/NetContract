"""Read imported Salesforce network evidence and match approved signal contracts.

Uses structured synthetic observations, not generated explanations, as evidence.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import re

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .seeded_network_import import digest


class NetworkContext(BaseModel):
    model_config = ConfigDict(extra='forbid')
    lab_namespace: str = Field(pattern=r'^[A-Za-z0-9_.:-]{1,120}$')
    max_age_seconds: int = Field(default=900, ge=1, le=86400)
    evidence_object: str = 'MIM_NetworkEvidence__c'
    evidence_key: str = 'SourceKey__c'
    evidence_node_key: str = 'NodeKey__c'
    evidence_namespace: str = 'LabNamespace__c'
    evidence_kind: str = 'EvidenceKind__c'
    evidence_json: str = 'EvidenceJSON__c'
    evidence_digest: str = 'SourceDigest__c'
    evidence_provenance: str = 'ProvenanceKind__c'
    catalog_object: str = 'MIM_DIP__c'
    catalog_json: str = 'ContractJSON__c'
    catalog_digest: str = 'ContractDigest__c'
    catalog_key: str = 'CatalogKey__c'
    catalog_review: str = 'CatalogReviewStatus__c'
    catalog_provenance: str = 'ProvenanceKind__c'

    @model_validator(mode='after')
    def identifiers(self):
        for key, value in self.model_dump().items():
            if key not in {'lab_namespace', 'max_age_seconds'} and not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,79}__c', value):
                raise ValueError('Use explicit custom Salesforce API identifiers')
        return self


def read_context(settings, node_key, read_query):
    if not isinstance(node_key, str) or not re.fullmatch(r'[a-f0-9]{64}', node_key):
        raise HTTPException(409, 'Incident requires the imported node SourceKey in its configured node_key field')
    evidence_fields = sorted({settings.evidence_key, settings.evidence_node_key, settings.evidence_namespace,
                              settings.evidence_kind, settings.evidence_json, settings.evidence_digest,
                              settings.evidence_provenance})
    evidence = read_query(
        f"SELECT Id, LastModifiedDate, {', '.join(evidence_fields)} FROM {settings.evidence_object} "
        f"WHERE {settings.evidence_node_key} = '{node_key}' "
        f"AND {settings.evidence_namespace} = '{settings.lab_namespace}' "
        f"AND {settings.evidence_kind} = 'observation' LIMIT 201")
    if len(evidence) > 200:
        raise HTTPException(409, 'Node evidence exceeds the bounded context window; archive/review history before retrying')
    catalog_fields = sorted({settings.catalog_json, settings.catalog_digest, settings.catalog_key,
                             settings.catalog_review, settings.catalog_provenance})
    catalog = read_query(
        f"SELECT Id, LastModifiedDate, {', '.join(catalog_fields)} FROM {settings.catalog_object} "
        f"WHERE {settings.catalog_review} = 'approved' "
        f"AND {settings.catalog_provenance} = 'synthetic' LIMIT 1001")
    if len(catalog) > 1000:
        raise HTTPException(409, 'Approved catalog exceeds the bounded context window')
    return evidence, catalog


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Missing observation timestamp')
    value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('Observation timestamps require a timezone')
    return value.astimezone(timezone.utc)


def checked_json(row, field, hash_field):
    raw = row.get(field)
    if not isinstance(raw, str) or len(raw) > 131072:
        raise ValueError('Invalid stored evidence JSON')
    value = json.loads(raw)
    if not isinstance(value, dict) or digest(value) != row.get(hash_field):
        raise ValueError('Stored content digest does not match')
    return value


def discover_contracts(evidence, contracts):
    """Reuse the original network_mop_catalog structured matching semantics.

    This is advisory; a true synthetic signal never authorizes execution.
    """
    if evidence['evidence_stale'] or evidence['latest']['status'] != 'attention':
        return {'status': 'no_match', 'candidates': [], 'recommended_dip_id': None,
                'execution_enabled': False, 'approval_evidence_trusted': False,
                'method': 'synthetic_observation_contract_v1'}
    signals = evidence['latest']['sample'].get('alarm_observations', {})
    candidates = [deepcopy(record) for record in contracts
                  if signals.get(record['trigger']['signal']) is True]
    return {'status': 'recommended' if len(candidates) == 1 else ('ambiguous' if candidates else 'no_match'),
            'method': 'synthetic_observation_contract_v1', 'candidates': candidates,
            'recommended_dip_id': candidates[0]['dip_id'] if len(candidates) == 1 else None,
            'execution_enabled': False, 'approval_evidence_trusted': False}


def evaluate_context(settings, node_key, service, evidence_rows, catalog_rows, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(service, str) or not service.strip():
        raise HTTPException(409, 'Incident requires an explicit service for network context matching')
    if not evidence_rows:
        raise HTTPException(409, 'No imported observations for this incident node and lab; export and import a fresh lab snapshot')
    try:
        observations = []
        for row in evidence_rows:
            payload = checked_json(row, settings.evidence_json, settings.evidence_digest)
            expected_node = digest({'namespace': settings.lab_namespace, 'kind': 'node', 'identity': payload['device_id']})
            identity = [payload['device_id'], payload['observed_at'], digest(payload)]
            expected_key = digest({'namespace': settings.lab_namespace, 'kind': 'observation', 'identity': identity})
            if (row.get(settings.evidence_kind) != 'observation'
                    or row.get(settings.evidence_namespace) != settings.lab_namespace
                    or row.get(settings.evidence_node_key) != node_key or expected_node != node_key
                    or row.get(settings.evidence_key) != expected_key
                    or row.get(settings.evidence_provenance) != 'synthetic'
                    or payload.get('simulation_only') is not True
                    or not isinstance(payload.get('sample'), dict)):
                raise ValueError('Unlinked or non-synthetic observation')
            observations.append((timestamp(payload['observed_at']), row, payload))
        observations.sort(key=lambda item: item[0], reverse=True)
        when, selected_row, latest = observations[0]
        if any(item[0] == when and digest(item[2]) != digest(latest) for item in observations[1:]):
            raise ValueError('Conflicting latest observations')
        age = (now - when).total_seconds()
        if age < -30 or age > settings.max_age_seconds:
            raise ValueError('Latest observation is stale or from the future')
        contracts, provenance = [], []
        identifiers = set()
        for row in catalog_rows:
            contract = checked_json(row, settings.catalog_json, settings.catalog_digest)
            if (row.get(settings.catalog_review) != 'approved'
                    or row.get(settings.catalog_provenance) != 'synthetic'
                    or contract.get('provenance', {}).get('kind') != 'synthetic'
                    or contract.get('execution_enabled') is not False):
                raise ValueError('Unapproved or non-synthetic catalog contract')
            if contract.get('service') not in {service, '*'}:
                continue
            trigger = contract.get('trigger', {})
            if (not isinstance(trigger.get('signal'), str) or trigger.get('equals') is not True
                    or trigger.get('requires_fresh') is not True):
                raise ValueError('Unsupported procedure trigger')
            identifier = contract['dip_id']
            key = digest({'dip_id': identifier, 'version': contract.get('contract_version', '1')})
            if identifier in identifiers or row.get(settings.catalog_key) != key:
                raise ValueError('Duplicate or inconsistent catalog identity')
            identifiers.add(identifier)
            contracts.append(contract)
            provenance.append({'record_id': row['Id'], 'catalog_key': key,
                               'digest': row[settings.catalog_digest], 'last_modified': row.get('LastModifiedDate')})
        signals = latest['sample'].get('alarm_observations', {})
        if not isinstance(signals, dict):
            raise ValueError('Invalid structured observations')
        result = discover_contracts({'evidence_stale': False, 'latest': latest}, contracts)
        selected = next((contract for contract in contracts if contract['dip_id'] == result['recommended_dip_id']), None)
        source = {'lab_namespace': settings.lab_namespace, 'node_key': node_key,
                  'observation_record_id': selected_row['Id'], 'observed_at': latest['observed_at'],
                  'age_seconds': max(age, 0), 'max_age_seconds': settings.max_age_seconds,
                  'observation_digest': digest(latest), 'catalog_records': provenance,
                  'provenance': 'synthetic', 'freshness_verified_at': now.isoformat(),
                  'authorization_evidence_trusted': False}
        result['reason'] = ('Exactly one approved procedure matches an explicit true signal in the latest fresh synthetic observation.'
                            if selected else 'No unique supported procedure; review node status, explicit signals and approved service-scoped catalog.')
        result['evidence_digest'] = digest({'context': source, 'recommendation': result})
        return {'recommendation': result, 'plan': selected, 'network_evidence': source,
                'approval_status': 'requires_human_review', 'write_back_enabled': False, 'execution_enabled': False}
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HTTPException(409, 'Network context cannot support a decision: ' + str(exc)) from exc
