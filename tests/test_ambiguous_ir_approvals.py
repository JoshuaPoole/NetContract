"""Duplicate model names must not result in implicit cross-file approvals."""
import pytest

from app.intermediate_representation import Evidence, IRField, IRNode, RepositoryIR
from app.ir_salesforce_bridge import ir_to_analysis


def test_duplicate_field_source_requires_disambiguation():
    nodes = []
    for index, filename in enumerate(("crm/models.py", "billing/models.py")):
        nodes.append(IRNode(
            id=f"model:{index}",
            kind="model_candidate",
            name="Customer",
            evidence=Evidence(source_file=filename),
            fields=[IRField(
                source="Customer.email",
                proposed_target="Email",
                proposed_type="Email",
                evidence=Evidence(source_file=filename, line=3),
            )],
        ))
    ir = RepositoryIR(repository="sample.zip", nodes=nodes)
    analysis = ir_to_analysis(ir)
    assert all(field.status == "review" for module in analysis.modules for field in module.fields)
    with pytest.raises(ValueError, match="Ambiguous source fields"):
        ir_to_analysis(ir, {"Customer.email"})

