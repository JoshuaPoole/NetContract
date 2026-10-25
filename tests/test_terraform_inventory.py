"""Terraform evidence must come from declarations, never comments or state."""
import json

from app.terraform_inventory import discover_terraform


def test_hcl_inventory_ignores_comments_strings_nested_blocks_and_heredocs():
    source = '''# resource "aws_instance" "comment" {}
/* module "commented" { } */
locals {
  text = "resource \\"aws_instance\\" \\"quoted\\" {}"
  policy = <<-END
resource "aws_instance" "heredoc" {}
END
}
resource "aws_instance" "legacy" {
  nested { resource "fake" "nested" {} }
  password = "DO_NOT_RETURN"
}
data "aws_vpc" "existing" {}
module "network" { source = "./modules/network" }
provider "aws" {}
variable "region" {}
output "endpoint" {}
'''
    result = discover_terraform([('infra/main.tf', source)])
    assert result['resource_count'] == 1
    assert [item['address'] for item in result['declarations']] == [
        'aws_instance.legacy', 'data.aws_vpc.existing', 'module.network',
        'provider.aws', 'variable.region', 'output.endpoint',
    ]
    resource = result['declarations'][0]
    assert resource['line'] == 9
    assert resource['module_path'] == 'infra'
    assert resource['runtime_status'] == 'unverified'
    assert 'DO_NOT_RETURN' not in json.dumps(result)


def test_json_inventory_and_duplicate_names_in_distinct_directories():
    result = discover_terraform([
        ('a/main.tf.json', json.dumps({'resource': {'aws_instance': {'app': {'secret': 'hidden'}}}})),
        ('b/main.tf', 'resource "aws_instance" "app" {}'),
        ('terraform.tfstate', '{"resources": []}'),
        ('bad.tf.json', '{invalid'),
    ])
    assert result['resource_count'] == 2
    assert result['declarations'][0]['line'] is None
    assert {item['module_path'] for item in result['declarations']} == {'a', 'b'}
    assert 'hidden' not in json.dumps(result)
    assert 'terraform.tfstate' not in result['files']
    assert any('Invalid Terraform JSON' in warning for warning in result['warnings'])


def test_missing_terraform_is_empty_and_unbalanced_hcl_is_marked_partial():
    assert discover_terraform([('main.py', '')])['declarations'] == []
    result = discover_terraform([('main.tf', 'resource "aws_instance" "app" {')])
    assert any('partial' in warning for warning in result['warnings'])
