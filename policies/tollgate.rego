# Tollgate request policy (ADR-0004).
#
# Python gathers facts; this file decides. Query: data.tollgate.decision
# Input shape:
#   app:     { name, team, risk_tier, restricted_data_approved }
#   request: { task, requested_tier, tier_override }
#   facts:   { pii_entities: [..], restricted_pii: [..], protected_attributes: [..] }
package tollgate

# --- Model approvals ---------------------------------------------------------
# Which model tiers are approved for which app risk tiers. A model enters "small" or
# "large" only after validation; "experimental" is approved for low-risk apps only.
tier_approvals := {
	"small": {"low", "medium", "high"},
	"large": {"low", "medium", "high"},
	"experimental": {"low"},
}

# Tasks whose output informs a credit decision (ECOA / Reg B scope).
credit_decision_tasks := {"assess"}

allowed_tiers contains tier if {
	some tier, risks in tier_approvals
	input.app.risk_tier in risks
}

# --- Deny rules ----------------------------------------------------------------
deny contains {
	"id": "protected_attribute_in_credit_task",
	"message": sprintf(
		"credit-decision tasks must not reference protected attributes: %v",
		[concat(", ", input.facts.protected_attributes)],
	),
} if {
	input.request.task in credit_decision_tasks
	count(input.facts.protected_attributes) > 0
}

deny contains {
	"id": "restricted_data_not_approved",
	"message": sprintf(
		"app '%s' is not approved to send restricted data (%v)",
		[input.app.name, concat(", ", input.facts.restricted_pii)],
	),
} if {
	not input.app.restricted_data_approved
	count(input.facts.restricted_pii) > 0
}

deny contains {
	"id": "model_tier_not_approved",
	"message": sprintf(
		"model tier '%s' is not approved for %s-risk apps",
		[input.request.requested_tier, input.app.risk_tier],
	),
} if {
	input.request.tier_override
	not input.request.requested_tier in allowed_tiers
}

# --- Decision ------------------------------------------------------------------
decision := {
	"allow": count(deny) == 0,
	"reasons": [r | some r in deny],
	"allowed_tiers": sort([t | some t in allowed_tiers]),
}
