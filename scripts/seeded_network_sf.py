"""Discover -> review schema -> explicitly upsert synthetic network seeds."""
import argparse
import csv
import json
from pathlib import Path
import shutil
import tempfile
import xml.etree.ElementTree as ET

from app.seeded_network_import import (
    NS, digest, discover, plan, schema_review, write_field_proposals,
)
from scripts.salesforce_deploy_playbook import run_sf

ORG = 'hackfest-developer'


def load_plan(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    expected = value.pop('review_digest')
    if digest(value) != expected or value.get('org_alias') != ORG:
        raise ValueError('Plan digest or target org changed; regenerate and review')
    value['review_digest'] = expected
    return value


def preflight(value, executable):
    reviews = []
    for batch in value['batches']:
        description = run_sf(executable, 'sobject', 'describe', '--sobject', batch['object'], '--target-org', ORG)
        reviews.append(schema_review(batch, description))
    return reviews


def apply(value, approval, executable):
    if approval != value['review_digest']:
        raise ValueError('Explicit approval must match the reviewed plan digest')
    # Check EVERY object before starting any write. Org changes can still cause a partial bulk job.
    reviews = preflight(value, executable)
    if any(review['missing_fields'] or review['blockers'] for review in reviews):
        raise ValueError('Schema or permissions are not ready; run check and review missing fields')
    receipts = []
    with tempfile.TemporaryDirectory(prefix='mim-seed-', ignore_cleanup_errors=True) as folder:
        for index, batch in enumerate(value['batches']):
            path = Path(folder) / f'{index}.csv'
            with path.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=sorted({key for row in batch['rows'] for key in row}))
                writer.writeheader()
                writer.writerows(batch['rows'])
            result = run_sf(executable, 'data', 'upsert', 'bulk', '--sobject', batch['object'],
                            '--external-id', batch['external_id'], '--file', str(path),
                            '--target-org', ORG, '--wait', '10')
            job = result.get('jobInfo', result)
            receipt = {'object': batch['object'], 'job_id': job.get('id') or result.get('jobId'),
                       'state': job.get('state'), 'failed': job.get('numberRecordsFailed'),
                       'processed': job.get('numberRecordsProcessed')}
            receipts.append(receipt)
            print(json.dumps(receipt), flush=True)
            if (receipt['state'] != 'JobComplete' or str(receipt['failed']) != '0'
                    or str(receipt['processed']) != str(len(batch['rows']))):
                raise RuntimeError('Import is incomplete or has failures. Retain the printed job ID, inspect Salesforce results, and retry the same reviewed keys; success is not assumed.')
    return receipts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    discover_parser = commands.add_parser('plan')
    discover_parser.add_argument('--source', required=True, type=Path)
    discover_parser.add_argument('--namespace', required=True)
    discover_parser.add_argument('--mapping', type=Path)
    discover_parser.add_argument('--out', required=True, type=Path)
    for name in ('check', 'apply'):
        sub = commands.add_parser(name)
        sub.add_argument('--plan', required=True, type=Path)
        if name == 'check':
            sub.add_argument('--out', required=True, type=Path)
            sub.add_argument('--propose-new-object', action='append', default=[])
        else:
            sub.add_argument('--approve-digest', required=True)
    args = parser.parse_args(argv)
    if args.command == 'plan':
        mapping = json.loads(args.mapping.read_text(encoding='utf-8')) if args.mapping else None
        value = plan(discover(args.source, args.namespace), mapping)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(value, indent=2), encoding='utf-8')
        print(json.dumps({'review_digest': value['review_digest'], 'counts': {b['object']: len(b['rows']) for b in value['batches']}, 'warnings': value['warnings']}))
        return
    value = load_plan(args.plan)
    executable = shutil.which('sf.cmd') or shutil.which('sf')
    if not executable:
        raise ValueError('Install Salesforce CLI and authenticate hackfest-developer')
    if args.command == 'apply':
        apply(value, args.approve_digest, executable)
        return
    if args.out.exists() and any(args.out.iterdir()):
        raise ValueError('Choose an empty schema review output directory')
    reviews = []
    scope = {b['object'] for b in value['batches']}
    if set(args.propose_new_object) - scope:
        raise ValueError('New object proposal must be in the reviewed import scope')
    for batch in value['batches']:
        new = batch['object'] in args.propose_new_object
        description = ({'fields': [], 'createable': True, 'updateable': True} if new else
                       run_sf(executable, 'sobject', 'describe', '--sobject', batch['object'], '--target-org', ORG))
        review = schema_review(batch, description)
        review['new_object_proposal'] = new
        reviews.append(review)
        destination = args.out / 'force-app/main/default'
        write_field_proposals(review, destination)
        if new:
            root = ET.Element('{' + NS + '}CustomObject')
            for key, text in [('deploymentStatus', 'Deployed'), ('label', 'MIM Network Evidence'),
                              ('pluralLabel', 'MIM Network Evidence'), ('sharingModel', 'Private')]:
                ET.SubElement(root, '{' + NS + '}' + key).text = text
            name_field = ET.SubElement(root, '{' + NS + '}nameField')
            for key, text in [('label', 'Evidence Number'), ('type', 'AutoNumber'), ('displayFormat', 'EVD-{000000}')]:
                ET.SubElement(name_field, '{' + NS + '}' + key).text = text
            folder = destination / 'objects' / batch['object']
            folder.mkdir(parents=True, exist_ok=True)
            ET.ElementTree(root).write(folder / (batch['object'] + '.object-meta.xml'), encoding='utf-8', xml_declaration=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'sfdx-project.json').write_text(json.dumps({'packageDirectories': [{'path': 'force-app', 'default': True}], 'sourceApiVersion': '65.0'}))
    (args.out / 'schema-review.json').write_text(json.dumps({'review_digest': value['review_digest'], 'objects': reviews}, indent=2))
    print(json.dumps(reviews, indent=2))


if __name__ == '__main__':
    main()
