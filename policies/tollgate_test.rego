package tollgate_test

import data.tollgate

base_input := {
	"app": {"name": "kyc-review", "team": "lending-ops", "risk_tier": "high", "restricted_data_approved": true},
	"request": {"task": "extract", "requested_tier": "small", "tier_override": false},
	"facts": {"pii_entities": [], "restricted_pii": [], "protected_attributes": []},
}

test_clean_request_allowed if {
	d := tollgate.decision with input as base_input
	d.allow
	d.allowed_tiers == ["large", "small"]
}

test_protected_attribute_in_assess_denied if {
	inp := json.patch(base_input, [
		{"op": "replace", "path": "/request/task", "value": "assess"},
		{"op": "replace", "path": "/facts/protected_attributes", "value": ["religion"]},
	])
	d := tollgate.decision with input as inp
	not d.allow
	d.reasons[0].id == "protected_attribute_in_credit_task"
}

test_protected_attribute_outside_credit_task_allowed if {
	inp := json.patch(base_input, [{"op": "replace", "path": "/facts/protected_attributes", "value": ["age"]}])
	d := tollgate.decision with input as inp
	d.allow
}

test_restricted_pii_from_unapproved_app_denied if {
	inp := json.patch(base_input, [
		{"op": "replace", "path": "/app/restricted_data_approved", "value": false},
		{"op": "replace", "path": "/facts/restricted_pii", "value": ["US_SSN"]},
	])
	d := tollgate.decision with input as inp
	not d.allow
	d.reasons[0].id == "restricted_data_not_approved"
}

test_restricted_pii_from_approved_app_allowed if {
	inp := json.patch(base_input, [{"op": "replace", "path": "/facts/restricted_pii", "value": ["US_SSN"]}])
	d := tollgate.decision with input as inp
	d.allow
}

test_experimental_tier_denied_for_high_risk if {
	inp := json.patch(base_input, [
		{"op": "replace", "path": "/request/requested_tier", "value": "experimental"},
		{"op": "replace", "path": "/request/tier_override", "value": true},
	])
	d := tollgate.decision with input as inp
	not d.allow
	d.reasons[0].id == "model_tier_not_approved"
}

test_experimental_tier_allowed_for_low_risk if {
	inp := json.patch(base_input, [
		{"op": "replace", "path": "/app/risk_tier", "value": "low"},
		{"op": "replace", "path": "/request/requested_tier", "value": "experimental"},
		{"op": "replace", "path": "/request/tier_override", "value": true},
	])
	d := tollgate.decision with input as inp
	d.allow
	"experimental" in d.allowed_tiers
}

test_multiple_violations_all_reported if {
	inp := json.patch(base_input, [
		{"op": "replace", "path": "/app/restricted_data_approved", "value": false},
		{"op": "replace", "path": "/request/task", "value": "assess"},
		{"op": "replace", "path": "/facts/restricted_pii", "value": ["US_SSN"]},
		{"op": "replace", "path": "/facts/protected_attributes", "value": ["race_or_color"]},
	])
	d := tollgate.decision with input as inp
	not d.allow
	count(d.reasons) == 2
}
