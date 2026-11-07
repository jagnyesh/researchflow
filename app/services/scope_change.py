"""Impact analysis for researcher-initiated scope changes (#343).

A deterministic rule over which requirement fields changed; the reviewer of
the resulting scope_change approval decides what happens next.
"""

from typing import Any, Dict


def analyze_scope_change_impact(requested_changes: Dict[str, Any]) -> Dict[str, Any]:
    impact = {
        "severity": "medium",
        "requires_rework": False,
        "restart_from_state": None,
        "estimated_delay_hours": 0,
        "affected_components": [],
    }

    if "inclusion_criteria" in requested_changes or "exclusion_criteria" in requested_changes:
        impact["severity"] = "high"
        impact["requires_rework"] = True
        impact["restart_from_state"] = "requirements_gathering"
        impact["estimated_delay_hours"] = 24
        impact["affected_components"].extend(["phenotype", "extraction", "qa"])

    elif "data_elements" in requested_changes:
        impact["severity"] = "medium"
        impact["requires_rework"] = True
        impact["restart_from_state"] = "feasibility_validation"
        impact["estimated_delay_hours"] = 12
        impact["affected_components"].extend(["extraction", "qa"])

    elif "time_period_start" in requested_changes or "time_period_end" in requested_changes:
        impact["severity"] = "low"
        impact["requires_rework"] = True
        impact["restart_from_state"] = "feasibility_validation"
        impact["estimated_delay_hours"] = 6
        impact["affected_components"].append("phenotype")

    return impact
