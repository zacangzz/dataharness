# Dataset Generators

This directory contains reusable scripts for generating local DataHarness test
datasets.

## Synthetic HR Workspace Fixture

`generate_employee_workspace_fixture.py` creates a synthetic employee dataset
for workspace analysis workflows.

Default output:

```bash
uv run python datasets/generate_employee_workspace_fixture.py
```

This writes to:

```text
dist/workspaces/w_0001/data
```

Generated files:

- `employees.csv` - current employee roster with synthetic PII-like fields,
  active/inactive status, salary, department, manager, role, and review fields.
- `departments.csv` - department reference data with divisions, cost centers,
  budgets, locations, headcount targets, and manager ids.
- `employment_history.csv` - event history tied to `employee_id`, including
  hires, promotions, job changes, transfers, salary increments, and
  terminations.
- `notes.md` - short workspace note describing the files.

The default fixture generates 2,000 employees with about 20% attrition. Employee
status is restricted to `active` or `inactive`. Every employee has exactly one
hire event, and every inactive employee has exactly one matching termination
event. Termination dates are weighted toward later months so attrition increases
across the two-year history window.

Useful commands:

```bash
# Generate into a scratch directory.
uv run python datasets/generate_employee_workspace_fixture.py \
  --output-dir /tmp/hr-fixture

# Generate a larger deterministic fixture.
uv run python datasets/generate_employee_workspace_fixture.py \
  --employee-count 5000 \
  --attrition-rate 0.18 \
  --seed 42

# Validate existing generated files without rewriting them.
uv run python datasets/generate_employee_workspace_fixture.py \
  --output-dir dist/workspaces/w_0001/data \
  --validate-only
```

All names, contact details, SSNs, addresses, salaries, and history rows are
randomly generated fixture data. The PII-like fields are synthetic and must not
be treated as real personal information.
