Return strict JSON only for one executable step contract.

Required fields:
- `step_id`
- `code`
- `inputs`
- `expected_schema`
- `report_required`

Rules:
- The code must match the requested step and nothing broader.
- The expected schema must describe the structured result the harness will validate.
- Prefer explicit inputs over implicit assumptions.
