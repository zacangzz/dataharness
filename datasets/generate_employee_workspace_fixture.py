#!/usr/bin/env python3
"""Generate a synthetic HR workspace fixture for DataHarness.

The default command recreates the employee fixture shape currently used by
``dist/workspaces/w_0001/data``:

    uv run python datasets/generate_employee_workspace_fixture.py

The generated dataset is intentionally synthetic. It includes PII-like fields
so local analysis workflows can exercise joins, redaction, summarization, and
reporting paths without using real personal information.

Files written:
    departments.csv
        Department reference data with divisions, cost centers, locations,
        budgets, headcount targets, and department manager ids.

    employees.csv
        Current employee roster with generated PII-like fields, active/inactive
        employment status, salary, role, department, manager, and review data.

    employment_history.csv
        Event history keyed by employee_id. Every employee has exactly one hire
        event. Every inactive employee has exactly one termination event.
        Promotion, job-change, transfer, and salary events preserve old/new
        values so each employee history can be replayed into the final roster.

    notes.md
        Short human-readable description for DataHarness file inspection.

Useful examples:
    # Generate the default fixture into the packaged workspace data directory.
    uv run python datasets/generate_employee_workspace_fixture.py

    # Generate into a scratch directory without touching dist/.
    uv run python datasets/generate_employee_workspace_fixture.py --output-dir /tmp/hr-fixture

    # Create a larger fixture with a different deterministic seed.
    uv run python datasets/generate_employee_workspace_fixture.py \\
        --employee-count 5000 --attrition-rate 0.18 --seed 42

    # Validate an existing generated fixture.
    uv run python datasets/generate_employee_workspace_fixture.py \\
        --output-dir dist/workspaces/w_0001/data --validate-only
"""

from __future__ import annotations

import argparse
import csv
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable


DEFAULT_OUTPUT_DIR = Path("dist/workspaces/w_0001/data")
DEFAULT_SEED = 20262514
DEFAULT_EMPLOYEE_COUNT = 2000
DEFAULT_ATTRITION_RATE = 0.20
DEFAULT_HISTORY_START = date(2024, 5, 15)
DEFAULT_HISTORY_END = date(2026, 5, 14)


FIRST_NAMES = [
    "Aarav",
    "Abigail",
    "Aisha",
    "Alexander",
    "Amara",
    "Amelia",
    "Andre",
    "Anika",
    "Arjun",
    "Avery",
    "Benjamin",
    "Bianca",
    "Caleb",
    "Camila",
    "Carlos",
    "Charlotte",
    "Chloe",
    "Daniel",
    "Daria",
    "David",
    "Diego",
    "Elena",
    "Eli",
    "Elijah",
    "Emily",
    "Emma",
    "Ethan",
    "Fatima",
    "Felix",
    "Gabriel",
    "Grace",
    "Hana",
    "Harper",
    "Hiro",
    "Imani",
    "Isaac",
    "Isabella",
    "Jamal",
    "James",
    "Jasmine",
    "Jonah",
    "Kai",
    "Keiko",
    "Laila",
    "Liam",
    "Lina",
    "Lucas",
    "Lucia",
    "Maya",
    "Mateo",
    "Mia",
    "Mila",
    "Mohamed",
    "Naomi",
    "Nia",
    "Noah",
    "Nora",
    "Oliver",
    "Olivia",
    "Omar",
    "Priya",
    "Rafael",
    "Rina",
    "Ryan",
    "Sana",
    "Samuel",
    "Sara",
    "Sofia",
    "Sophie",
    "Tariq",
    "Theo",
    "Valentina",
    "Victor",
    "Yara",
    "Yuki",
    "Zara",
    "Zoe",
]

LAST_NAMES = [
    "Adams",
    "Ahmed",
    "Anderson",
    "Baker",
    "Bennett",
    "Brown",
    "Campbell",
    "Carter",
    "Chen",
    "Clark",
    "Davis",
    "Diaz",
    "Edwards",
    "Evans",
    "Fisher",
    "Flores",
    "Garcia",
    "Gomez",
    "Green",
    "Gupta",
    "Hall",
    "Harris",
    "Hernandez",
    "Hill",
    "Hughes",
    "Ito",
    "Jackson",
    "Johnson",
    "Jones",
    "Khan",
    "Kim",
    "King",
    "Kumar",
    "Lee",
    "Lewis",
    "Lopez",
    "Martin",
    "Martinez",
    "Miller",
    "Mitchell",
    "Moore",
    "Murphy",
    "Nguyen",
    "Patel",
    "Perez",
    "Phillips",
    "Ramirez",
    "Reed",
    "Rivera",
    "Roberts",
    "Robinson",
    "Rodriguez",
    "Ross",
    "Sanchez",
    "Scott",
    "Shah",
    "Singh",
    "Smith",
    "Taylor",
    "Thomas",
    "Thompson",
    "Torres",
    "Turner",
    "Walker",
    "Wang",
    "White",
    "Williams",
    "Wilson",
    "Wong",
    "Wright",
    "Young",
    "Zhang",
]

STREET_NAMES = [
    "Maple",
    "Oak",
    "Pine",
    "Cedar",
    "Elm",
    "Willow",
    "Lake",
    "Hill",
    "View",
    "River",
    "Market",
    "Union",
    "Park",
    "Washington",
    "Lincoln",
    "Franklin",
    "Madison",
    "Adams",
    "Jackson",
    "Monroe",
]

STREET_TYPES = ["St", "Ave", "Blvd", "Dr", "Ln", "Rd", "Way", "Ct", "Pl"]

LOCATIONS = [
    ("Austin", "TX", "78701"),
    ("Atlanta", "GA", "30303"),
    ("Boston", "MA", "02108"),
    ("Chicago", "IL", "60601"),
    ("Denver", "CO", "80202"),
    ("Los Angeles", "CA", "90012"),
    ("Miami", "FL", "33130"),
    ("New York", "NY", "10001"),
    ("Portland", "OR", "97204"),
    ("Raleigh", "NC", "27601"),
    ("San Diego", "CA", "92101"),
    ("San Francisco", "CA", "94105"),
    ("Seattle", "WA", "98101"),
    ("Washington", "DC", "20001"),
]

WORK_LOCATIONS = [
    "Austin HQ",
    "Atlanta Office",
    "Boston Office",
    "Chicago Office",
    "Denver Office",
    "New York Office",
    "San Francisco HQ",
    "Seattle Office",
    "Remote - US",
]

DIVISIONS = {
    "Engineering": [
        "Platform Engineering",
        "Data Engineering",
        "Machine Learning",
        "Product Engineering",
    ],
    "Product": ["Product Management", "Design", "Research"],
    "Revenue": ["Sales", "Customer Success", "Marketing", "Revenue Operations"],
    "Operations": ["People Operations", "Finance", "Legal", "IT", "Facilities"],
    "Strategy": ["Business Operations", "Corporate Development", "Analytics"],
}

JOB_CATALOG = {
    "Platform Engineering": [
        "Software Engineer",
        "Senior Software Engineer",
        "Staff Software Engineer",
        "Engineering Manager",
    ],
    "Data Engineering": [
        "Data Engineer",
        "Senior Data Engineer",
        "Analytics Engineer",
        "Data Engineering Manager",
    ],
    "Machine Learning": [
        "Machine Learning Engineer",
        "Applied Scientist",
        "ML Platform Engineer",
        "ML Manager",
    ],
    "Product Engineering": [
        "Frontend Engineer",
        "Backend Engineer",
        "Full Stack Engineer",
        "Product Engineering Manager",
    ],
    "Product Management": [
        "Product Manager",
        "Senior Product Manager",
        "Group Product Manager",
        "Director of Product",
    ],
    "Design": [
        "Product Designer",
        "Senior Product Designer",
        "Design Manager",
        "Content Designer",
    ],
    "Research": [
        "UX Researcher",
        "Senior UX Researcher",
        "Research Manager",
        "Research Operations Lead",
    ],
    "Sales": [
        "Account Executive",
        "Senior Account Executive",
        "Sales Manager",
        "Enterprise Account Executive",
    ],
    "Customer Success": [
        "Customer Success Manager",
        "Implementation Manager",
        "Support Specialist",
        "Customer Success Director",
    ],
    "Marketing": [
        "Marketing Manager",
        "Demand Generation Manager",
        "Content Strategist",
        "Marketing Director",
    ],
    "Revenue Operations": [
        "Revenue Operations Analyst",
        "Sales Operations Manager",
        "CRM Administrator",
        "Revenue Operations Director",
    ],
    "People Operations": [
        "HR Generalist",
        "Recruiter",
        "People Partner",
        "People Operations Manager",
    ],
    "Finance": [
        "Financial Analyst",
        "Senior Financial Analyst",
        "Accounting Manager",
        "Finance Director",
    ],
    "Legal": [
        "Legal Counsel",
        "Contracts Manager",
        "Compliance Manager",
        "Senior Legal Counsel",
    ],
    "IT": ["IT Specialist", "Systems Administrator", "Security Analyst", "IT Manager"],
    "Facilities": [
        "Facilities Coordinator",
        "Office Manager",
        "Workplace Manager",
        "Facilities Director",
    ],
    "Business Operations": [
        "Business Operations Analyst",
        "Strategy Manager",
        "Program Manager",
        "Business Operations Director",
    ],
    "Corporate Development": [
        "Corporate Development Analyst",
        "Partnerships Manager",
        "Corporate Development Manager",
        "Director of Partnerships",
    ],
    "Analytics": [
        "Data Analyst",
        "Senior Data Analyst",
        "BI Developer",
        "Analytics Manager",
    ],
}

LEVEL_TOKENS = {
    "Director": 6,
    "Group": 6,
    "Staff": 5,
    "Manager": 5,
    "Lead": 5,
    "Senior": 4,
    "Counsel": 4,
    "Engineer": 3,
    "Designer": 3,
    "Researcher": 3,
    "Analyst": 2,
    "Specialist": 2,
    "Coordinator": 2,
    "Administrator": 2,
}

BASE_SALARY_BY_LEVEL = {
    1: 52_000,
    2: 68_000,
    3: 92_000,
    4: 122_000,
    5: 158_000,
    6: 205_000,
    7: 255_000,
}

EVENT_REASONS = {
    "hire": ["new hire", "replacement role", "team expansion"],
    "promotion": ["promotion cycle", "expanded scope", "leadership readiness"],
    "job_change": ["role alignment", "career development", "business need"],
    "transfer": ["internal transfer", "location preference", "team reorganization"],
    "salary_increment": [
        "annual compensation review",
        "market adjustment",
        "retention adjustment",
    ],
    "termination": [
        "voluntary resignation",
        "role eliminated",
        "contract ended",
        "performance separation",
        "mutual separation",
    ],
}


CsvRow = dict[str, str]


@dataclass(frozen=True)
class GenerationConfig:
    """Inputs that control fixture size, timeline, and deterministic randomness."""

    output_dir: Path
    employee_count: int = DEFAULT_EMPLOYEE_COUNT
    attrition_rate: float = DEFAULT_ATTRITION_RATE
    seed: int = DEFAULT_SEED
    history_start: date = DEFAULT_HISTORY_START
    history_end: date = DEFAULT_HISTORY_END

    @property
    def inactive_target(self) -> int:
        return round(self.employee_count * self.attrition_rate)


@dataclass(frozen=True)
class FixtureSummary:
    """Counts returned after generation or validation."""

    employee_count: int
    department_count: int
    history_count: int
    active_count: int
    inactive_count: int
    event_counts: Counter[str]
    quarter_terminations: Counter[str]

    @property
    def attrition_rate(self) -> float:
        if self.employee_count == 0:
            return 0.0
        return self.inactive_count / self.employee_count


class FixtureValidationError(ValueError):
    """Raised when generated files do not satisfy the fixture contract."""


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def iso(day: date) -> str:
    return day.isoformat()


def random_date(rng: random.Random, start: date, end: date) -> date:
    if end < start:
        return start
    return start + timedelta(days=rng.randint(0, (end - start).days))


def month_add(start: date, offset: int) -> date:
    month_index = start.month - 1 + offset
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def month_end(start: date) -> date:
    return month_add(start, 1) - timedelta(days=1)


def parse_level(title: str) -> int:
    for token, level in LEVEL_TOKENS.items():
        if token in title:
            return level
    return 3


def salary_for(rng: random.Random, level: int, department: str) -> int:
    multiplier = 1.0
    if department in {
        "Machine Learning",
        "Platform Engineering",
        "Data Engineering",
        "Product Engineering",
    }:
        multiplier = 1.18
    elif department in {"Sales", "Product Management", "Corporate Development"}:
        multiplier = 1.10
    elif department in {"Facilities", "People Operations", "Customer Success"}:
        multiplier = 0.92
    return int(
        round(BASE_SALARY_BY_LEVEL[level] * multiplier * rng.uniform(0.88, 1.18) / 1000)
        * 1000
    )


def generate_increasing_termination_dates(
    rng: random.Random,
    config: GenerationConfig,
) -> list[date]:
    """Return termination dates whose volume increases over the history window."""

    month_count = (
        (config.history_end.year - config.history_start.year) * 12
        + config.history_end.month
        - config.history_start.month
        + 1
    )
    month_starts = [
        month_add(date(config.history_start.year, config.history_start.month, 1), index)
        for index in range(month_count)
    ]
    weights = [max(1, index + 1) ** 1.45 for index in range(month_count)]
    raw_counts = [
        weight / sum(weights) * config.inactive_target
        for weight in weights
    ]
    monthly_counts = [int(value) for value in raw_counts]

    while sum(monthly_counts) < config.inactive_target:
        fraction_order = sorted(
            range(len(raw_counts)),
            key=lambda index: raw_counts[index] - monthly_counts[index],
            reverse=True,
        )
        for index in fraction_order:
            if sum(monthly_counts) >= config.inactive_target:
                break
            monthly_counts[index] += 1

    while sum(monthly_counts) > config.inactive_target:
        index = max(range(len(monthly_counts)), key=lambda idx: monthly_counts[idx])
        monthly_counts[index] -= 1

    termination_dates: list[date] = []
    for month_start, count in zip(month_starts, monthly_counts, strict=True):
        start = max(month_start, config.history_start)
        end = min(month_end(month_start), config.history_end)
        for _ in range(count):
            termination_dates.append(random_date(rng, start, end))
    termination_dates.sort()
    return termination_dates


def make_departments(rng: random.Random) -> tuple[list[CsvRow], dict[str, CsvRow]]:
    rows: list[CsvRow] = []
    by_id: dict[str, CsvRow] = {}
    department_number = 1
    for division, names in DIVISIONS.items():
        for name in names:
            department_id = f"D{department_number:03d}"
            city, state, _ = rng.choice(LOCATIONS)
            row = {
                "department_id": department_id,
                "department_name": name,
                "division": division,
                "cost_center": f"CC-{division[:3].upper()}-{department_number:03d}",
                "location": f"{city}, {state}",
                "manager_employee_id": "",
                "budget_usd": str(rng.randrange(1_200_000, 12_500_001, 50_000)),
                "headcount_target": str(rng.randint(35, 180)),
            }
            rows.append(row)
            by_id[department_id] = row
            department_number += 1
    return rows, by_id


def blank_state() -> CsvRow:
    return {
        "department_id": "",
        "department_name": "",
        "job_title": "",
        "job_level": "",
        "salary_usd": "",
        "manager_employee_id": "",
    }


def add_history_event(
    rows: list[CsvRow],
    rng: random.Random,
    manager_pool: Iterable[str],
    employee_id: str,
    event_date: date,
    event_type: str,
    old_status: str,
    new_status: str,
    old: CsvRow,
    new: CsvRow,
    note: str,
) -> None:
    approvers = [manager for manager in manager_pool if manager != employee_id]
    rows.append(
        {
            "history_id": f"H{len(rows) + 1:06d}",
            "employee_id": employee_id,
            "event_date": iso(event_date),
            "event_type": event_type,
            "old_employment_status": old_status,
            "new_employment_status": new_status,
            "old_department_id": old.get("department_id", ""),
            "new_department_id": new.get("department_id", ""),
            "old_job_title": old.get("job_title", ""),
            "new_job_title": new.get("job_title", ""),
            "old_job_level": old.get("job_level", ""),
            "new_job_level": new.get("job_level", ""),
            "old_salary_usd": old.get("salary_usd", ""),
            "new_salary_usd": new.get("salary_usd", ""),
            "old_manager_employee_id": old.get("manager_employee_id", ""),
            "new_manager_employee_id": new.get("manager_employee_id", ""),
            "reason": rng.choice(EVENT_REASONS[event_type]),
            "approved_by_employee_id": rng.choice(approvers) if approvers else "E0001",
            "notes": note,
        }
    )


def generate_fixture(config: GenerationConfig) -> FixtureSummary:
    """Generate fixture CSVs and notes into config.output_dir."""

    rng = random.Random(config.seed)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    departments, department_by_id = make_departments(rng)
    termination_dates = generate_increasing_termination_dates(rng, config)
    inactive_ids = {
        f"E{index:04d}"
        for index in rng.sample(
            range(1, config.employee_count + 1),
            config.inactive_target,
        )
    }
    termination_by_employee = dict(zip(sorted(inactive_ids), termination_dates, strict=True))

    employees: list[CsvRow] = []
    history: list[CsvRow] = []
    used_emails: set[str] = set()
    used_ssn: set[str] = set()
    manager_candidates_by_dept: dict[str, list[str]] = {
        row["department_id"]: [] for row in departments
    }

    def manager_pool() -> list[str]:
        return [
            manager
            for managers in manager_candidates_by_dept.values()
            for manager in managers
        ]

    for index in range(1, config.employee_count + 1):
        employee_id = f"E{index:04d}"
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        preferred = first if rng.random() > 0.18 else rng.choice(FIRST_NAMES)
        email_base = f"{first}.{last}".lower().replace(" ", "")
        email = f"{email_base}@examplecorp.test"
        suffix = 2
        while email in used_emails:
            email = f"{email_base}{suffix}@examplecorp.test"
            suffix += 1
        used_emails.add(email)

        department = rng.choice(departments)
        department_id = department["department_id"]
        department_name = department["department_name"]
        title = rng.choice(JOB_CATALOG[department_name])
        level = parse_level(title)
        salary = salary_for(rng, level, department_name)
        termination_date = termination_by_employee.get(employee_id)
        hire_latest = (
            termination_date - timedelta(days=30)
            if termination_date
            else config.history_end - timedelta(days=14)
        )
        if rng.random() < 0.78:
            hire_date = random_date(
                rng,
                date(2011, 1, 1),
                min(config.history_start - timedelta(days=30), hire_latest),
            )
        else:
            hire_date = random_date(rng, config.history_start, hire_latest)

        manager_id = (
            rng.choice(manager_candidates_by_dept[department_id])
            if manager_candidates_by_dept[department_id] and rng.random() < 0.83
            else ""
        )
        current = {
            "department_id": department_id,
            "department_name": department_name,
            "job_title": title,
            "job_level": str(level),
            "salary_usd": str(salary),
            "manager_employee_id": manager_id,
        }
        add_history_event(
            history,
            rng,
            manager_pool(),
            employee_id,
            hire_date,
            "hire",
            "",
            "active",
            blank_state(),
            current.copy(),
            "Employee hired; initial role, department, manager, and salary recorded.",
        )

        movement_end = (
            termination_date - timedelta(days=1)
            if termination_date
            else config.history_end
        )
        events: list[tuple[date, int, str]] = []
        for review_date in (date(2025, 3, 1), date(2026, 3, 1)):
            if hire_date <= review_date <= movement_end and rng.random() < 0.88:
                review_event_date = min(
                    review_date + timedelta(days=rng.randint(0, 21)),
                    movement_end,
                )
                events.append((review_event_date, 2, "salary_increment"))

        earliest_event = max(hire_date + timedelta(days=14), config.history_start)
        movement_count = rng.choices([0, 1, 2, 3], weights=[36, 43, 17, 4], k=1)[0]
        if earliest_event <= movement_end:
            for _ in range(movement_count):
                event_type = rng.choices(
                    ["promotion", "job_change", "transfer", "salary_increment"],
                    weights=[28, 20, 22, 30],
                    k=1,
                )[0]
                events.append(
                    (random_date(rng, earliest_event, movement_end), 1, event_type)
                )
        events.sort(key=lambda item: (item[0], item[1]))

        for event_date, _, event_type in events:
            old = current.copy()
            if event_type == "salary_increment":
                current["salary_usd"] = str(
                    int(
                        round(
                            int(current["salary_usd"]) * rng.uniform(1.025, 1.085)
                            / 500
                        )
                        * 500
                    )
                )
                note = "Compensation updated during review or adjustment cycle."
            elif event_type == "promotion":
                possible = [
                    candidate
                    for candidate in JOB_CATALOG[current["department_name"]]
                    if parse_level(candidate) > int(current["job_level"])
                ]
                current["job_title"] = rng.choice(possible) if possible else current["job_title"]
                current["job_level"] = str(
                    min(7, max(int(current["job_level"]) + 1, parse_level(current["job_title"])))
                )
                current["salary_usd"] = str(
                    int(
                        round(
                            int(current["salary_usd"]) * rng.uniform(1.075, 1.18)
                            / 500
                        )
                        * 500
                    )
                )
                note = "Promotion recorded with expanded responsibilities."
            elif event_type == "job_change":
                current["job_title"] = rng.choice(JOB_CATALOG[current["department_name"]])
                current["job_level"] = str(
                    max(
                        1,
                        min(
                            7,
                            parse_level(current["job_title"]) + rng.choice([-1, 0, 0, 1]),
                        ),
                    )
                )
                current["salary_usd"] = str(
                    int(
                        round(
                            int(current["salary_usd"]) * rng.uniform(0.98, 1.12)
                            / 500
                        )
                        * 500
                    )
                )
                note = "Employee moved into a different role in the same department."
            else:
                new_department = rng.choice(
                    [
                        candidate
                        for candidate in departments
                        if candidate["department_id"] != current["department_id"]
                    ]
                )
                current["department_id"] = new_department["department_id"]
                current["department_name"] = new_department["department_name"]
                current["job_title"] = rng.choice(JOB_CATALOG[current["department_name"]])
                current["job_level"] = str(parse_level(current["job_title"]))
                current["salary_usd"] = str(
                    int(
                        round(
                            (
                                int(current["salary_usd"]) * rng.uniform(0.98, 1.10)
                                + salary_for(
                                    rng,
                                    int(current["job_level"]),
                                    current["department_name"],
                                )
                            )
                            / 2
                            / 500
                        )
                        * 500
                    )
                )
                current["manager_employee_id"] = (
                    rng.choice(manager_candidates_by_dept[current["department_id"]])
                    if manager_candidates_by_dept[current["department_id"]]
                    and rng.random() < 0.75
                    else ""
                )
                note = "Transfer completed between departments."

            add_history_event(
                history,
                rng,
                manager_pool(),
                employee_id,
                event_date,
                event_type,
                "active",
                "active",
                old,
                current.copy(),
                note,
            )

        status = "inactive" if termination_date else "active"
        termination_date_text = ""
        if termination_date:
            termination_date_text = iso(termination_date)
            add_history_event(
                history,
                rng,
                manager_pool(),
                employee_id,
                termination_date,
                "termination",
                "active",
                "inactive",
                current.copy(),
                current.copy(),
                "Employment ended; final role, department, manager, and salary retained for audit continuity.",
            )

        city, state, postal_code = rng.choice(LOCATIONS)
        ssn = f"9{rng.randint(10, 99):02d}-{rng.randint(10, 99):02d}-{rng.randint(1000, 9999):04d}"
        while ssn in used_ssn:
            ssn = f"9{rng.randint(10, 99):02d}-{rng.randint(10, 99):02d}-{rng.randint(1000, 9999):04d}"
        used_ssn.add(ssn)
        employment_type = rng.choices(
            ["full_time", "part_time", "contract"],
            weights=[79, 8, 13],
            k=1,
        )[0]
        last_review = rng.choice(
            [date(2025, 3, 15), date(2025, 9, 15), date(2026, 3, 15), ""]
        )
        rating = (
            rng.choice(
                [
                    "1-needs_improvement",
                    "2-developing",
                    "3-meets",
                    "4-exceeds",
                    "5-outstanding",
                ]
            )
            if status == "active"
            else ""
        )
        employee = {
            "employee_id": employee_id,
            "first_name": first,
            "last_name": last,
            "preferred_name": preferred,
            "email": email,
            "phone": f"+1-555-{rng.randint(200, 999):03d}-{rng.randint(1000, 9999):04d}",
            "date_of_birth": iso(random_date(rng, date(1962, 1, 1), date(2003, 12, 31))),
            "ssn": ssn,
            "home_address": f"{rng.randint(100, 9999)} {rng.choice(STREET_NAMES)} {rng.choice(STREET_TYPES)}",
            "city": city,
            "state": state,
            "postal_code": postal_code,
            "country": "US",
            "hire_date": iso(hire_date),
            "employment_status": status,
            "termination_date": termination_date_text,
            "department_id": current["department_id"],
            "department_name": current["department_name"],
            "job_title": current["job_title"],
            "job_level": current["job_level"],
            "manager_employee_id": current["manager_employee_id"],
            "work_location": rng.choice(WORK_LOCATIONS),
            "employment_type": employment_type,
            "salary_usd": current["salary_usd"],
            "bonus_target_pct": str(
                rng.choice([0, 5, 7, 10, 12, 15, 20, 25])
                if employment_type != "contract"
                else 0
            ),
            "performance_rating": rating,
            "last_review_date": iso(last_review) if isinstance(last_review, date) else "",
            "synthetic_pii": "true",
        }
        employees.append(employee)
        if status == "active" and int(current["job_level"]) >= 5:
            manager_candidates_by_dept[current["department_id"]].append(employee_id)

    fill_department_managers(
        rng,
        departments,
        department_by_id,
        employees,
        manager_candidates_by_dept,
    )
    sync_final_manager_history(employees, history)
    sort_and_number_history(history)
    write_fixture_files(config.output_dir, departments, employees, history)
    summary = validate_fixture(config.output_dir, config)
    return summary


def fill_department_managers(
    rng: random.Random,
    departments: list[CsvRow],
    department_by_id: dict[str, CsvRow],
    employees: list[CsvRow],
    manager_candidates_by_dept: dict[str, list[str]],
) -> None:
    for department in departments:
        candidates = manager_candidates_by_dept[department["department_id"]]
        if candidates:
            department["manager_employee_id"] = rng.choice(candidates)
        else:
            members = [
                employee["employee_id"]
                for employee in employees
                if employee["department_id"] == department["department_id"]
                and employee["employment_status"] == "active"
            ]
            department["manager_employee_id"] = rng.choice(members) if members else ""

    for employee in employees:
        if not employee["manager_employee_id"]:
            manager = department_by_id[employee["department_id"]]["manager_employee_id"]
            employee["manager_employee_id"] = (
                "" if manager == employee["employee_id"] else manager
            )


def sync_final_manager_history(employees: list[CsvRow], history: list[CsvRow]) -> None:
    """Align each employee's final history manager with employees.csv.

    Department manager ids are filled after all employees are generated. Some
    employees initially have a blank manager, then receive a department-level
    manager during that final pass. The roster is the current-state source of
    truth, so this updates the final history event to replay into the same
    manager id without changing earlier audit rows.
    """

    employee_by_id = {employee["employee_id"]: employee for employee in employees}
    rows_by_employee: dict[str, list[CsvRow]] = defaultdict(list)
    for row in history:
        rows_by_employee[row["employee_id"]].append(row)
    for employee_id, rows in rows_by_employee.items():
        rows.sort(key=lambda row: (row["event_date"], row["history_id"]))
        rows[-1]["new_manager_employee_id"] = employee_by_id[employee_id][
            "manager_employee_id"
        ]


def sort_and_number_history(history: list[CsvRow]) -> None:
    priority = {
        "hire": 0,
        "salary_increment": 1,
        "promotion": 1,
        "job_change": 1,
        "transfer": 1,
        "termination": 2,
    }
    history.sort(
        key=lambda row: (
            row["employee_id"],
            row["event_date"],
            priority.get(row["event_type"], 1),
            row["history_id"],
        )
    )
    for index, row in enumerate(history, start=1):
        row["history_id"] = f"H{index:06d}"


def write_csv(path: Path, rows: list[CsvRow]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_fixture_files(
    output_dir: Path,
    departments: list[CsvRow],
    employees: list[CsvRow],
    history: list[CsvRow],
) -> None:
    write_csv(output_dir / "departments.csv", departments)
    write_csv(output_dir / "employees.csv", employees)
    write_csv(output_dir / "employment_history.csv", history)
    (output_dir / "notes.md").write_text(
        "# Workspace notes\n\n"
        "Synthetic HR dataset for testing DataHarness file inspection, joins, analysis, and reporting workflows.\n\n"
        f"- `employees.csv` - {len(employees):,} synthetic employee records with generated PII fields, department assignment, current role, manager, salary, review attributes, active/inactive employment status, and termination date when applicable.\n"
        "- `departments.csv` - generated department reference data with divisions, cost centers, locations, budgets, headcount targets, and department manager ids.\n"
        "- `employment_history.csv` - about two years of synthetic employment events tied to `employee_id`, including hires, promotions, job changes, transfers, salary increments, terminations, old/new employment status, old/new salary, and old/new department or manager values. Terminations are weighted toward later months so attrition increases over the history period.\n\n"
        "All names, contact details, SSNs, addresses, salaries, and history rows are randomly generated fixture data. The PII-like fields are synthetic and must not be treated as real personal information.\n",
        encoding="utf-8",
    )


def read_csv(path: Path) -> list[CsvRow]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def validate_fixture(
    output_dir: Path,
    config: GenerationConfig | None = None,
) -> FixtureSummary:
    """Validate generated files and return a concise summary.

    The validation intentionally checks business-level invariants instead of
    exact row values, so the script can be reused with different seeds, employee
    counts, and attrition rates.
    """

    employees = read_csv(output_dir / "employees.csv")
    departments = read_csv(output_dir / "departments.csv")
    history = read_csv(output_dir / "employment_history.csv")
    employee_ids = {row["employee_id"] for row in employees}
    department_ids = {row["department_id"] for row in departments}
    by_employee: dict[str, list[CsvRow]] = defaultdict(list)
    errors: list[str] = []
    valid_statuses = {"active", "inactive"}

    if not employees:
        errors.append("employees.csv is empty")
    if config and len(employees) != config.employee_count:
        errors.append(f"expected {config.employee_count} employees, got {len(employees)}")
    if any(row["employment_status"] not in valid_statuses for row in employees):
        errors.append("employees.csv contains status outside active/inactive")
    if employees and "leave_start_date" in employees[0]:
        errors.append("employees.csv must not contain leave_start_date")

    for row in history:
        by_employee[row["employee_id"]].append(row)
        if row["employee_id"] not in employee_ids:
            errors.append(f"unknown employee in history: {row['employee_id']}")
        if row["event_type"] == "leave_start":
            errors.append(f"leave_start event remains: {row['history_id']}")
        for key in ("old_employment_status", "new_employment_status"):
            if row[key] and row[key] not in valid_statuses:
                errors.append(f"invalid history status {row[key]} in {row['history_id']}")
        for key in ("old_department_id", "new_department_id"):
            if row[key] and row[key] not in department_ids:
                errors.append(f"unknown department {row[key]} in {row['history_id']}")
        event_date = parse_date(row["event_date"])
        if config and row["event_type"] != "hire":
            if not (config.history_start <= event_date <= config.history_end):
                errors.append(
                    f"out-of-window non-hire event: {row['history_id']} {row['event_date']}"
                )

    for employee in employees:
        rows = sorted(
            by_employee.get(employee["employee_id"], []),
            key=lambda row: (row["event_date"], row["history_id"]),
        )
        hires = [row for row in rows if row["event_type"] == "hire"]
        terminations = [row for row in rows if row["event_type"] == "termination"]
        if len(hires) != 1:
            errors.append(
                f"{employee['employee_id']} expected one hire event, found {len(hires)}"
            )
        elif hires[0]["event_date"] != employee["hire_date"]:
            errors.append(f"{employee['employee_id']} hire date mismatch")

        if employee["employment_status"] == "inactive":
            if len(terminations) != 1:
                errors.append(
                    f"{employee['employee_id']} inactive expected one termination, found {len(terminations)}"
                )
            elif employee["termination_date"] != terminations[0]["event_date"]:
                errors.append(f"{employee['employee_id']} termination date mismatch")
        elif terminations:
            errors.append(f"{employee['employee_id']} active employee has termination event")

        if not rows:
            errors.append(f"{employee['employee_id']} has no history")
            continue

        last = rows[-1]
        for history_key, employee_key in (
            ("new_employment_status", "employment_status"),
            ("new_department_id", "department_id"),
            ("new_job_title", "job_title"),
            ("new_job_level", "job_level"),
            ("new_salary_usd", "salary_usd"),
            ("new_manager_employee_id", "manager_employee_id"),
        ):
            if last[history_key] != employee[employee_key]:
                errors.append(
                    f"{employee['employee_id']} final mismatch {history_key}={last[history_key]} "
                    f"{employee_key}={employee[employee_key]}"
                )
                break

        for previous, current in zip(rows, rows[1:]):
            for old_key, new_key in (
                ("old_employment_status", "new_employment_status"),
                ("old_department_id", "new_department_id"),
                ("old_job_title", "new_job_title"),
                ("old_job_level", "new_job_level"),
                ("old_salary_usd", "new_salary_usd"),
                ("old_manager_employee_id", "new_manager_employee_id"),
            ):
                if current[old_key] != previous[new_key]:
                    errors.append(
                        f"{employee['employee_id']} chain mismatch "
                        f"{previous['history_id']}->{current['history_id']} {old_key}"
                    )
                    break

    status_counts = Counter(row["employment_status"] for row in employees)
    event_counts = Counter(row["event_type"] for row in history)
    quarter_terminations: Counter[str] = Counter()
    for row in history:
        if row["event_type"] != "termination":
            continue
        event_date = parse_date(row["event_date"])
        quarter = ((event_date.month - 1) // 3) + 1
        quarter_terminations[f"{event_date.year}-Q{quarter}"] += 1

    inactive_count = status_counts["inactive"]
    attrition_rate = inactive_count / len(employees) if employees else 0.0
    if config:
        expected_attrition = config.inactive_target / config.employee_count
        if abs(attrition_rate - expected_attrition) > 0.005:
            errors.append(
                f"attrition rate expected about {expected_attrition:.1%}, got {attrition_rate:.1%}"
            )
        if event_counts["termination"] != inactive_count:
            errors.append(
                f"terminations {event_counts['termination']} must match inactive employees {inactive_count}"
            )
        quarters = expected_quarters(config.history_start, config.history_end)
        first_half = sum(quarter_terminations[quarter] for quarter in quarters[: len(quarters) // 2])
        second_half = sum(quarter_terminations[quarter] for quarter in quarters[len(quarters) // 2 :])
        if not second_half > first_half:
            errors.append(
                f"attrition should increase over time; first_half={first_half}, second_half={second_half}"
            )

    if errors:
        sample = "\n".join(f"- {error}" for error in errors[:30])
        raise FixtureValidationError(f"fixture validation failed:\n{sample}")

    return FixtureSummary(
        employee_count=len(employees),
        department_count=len(departments),
        history_count=len(history),
        active_count=status_counts["active"],
        inactive_count=inactive_count,
        event_counts=event_counts,
        quarter_terminations=quarter_terminations,
    )


def expected_quarters(start: date, end: date) -> list[str]:
    quarters: list[str] = []
    cursor = date(start.year, ((start.month - 1) // 3) * 3 + 1, 1)
    while cursor <= end:
        quarter = ((cursor.month - 1) // 3) + 1
        label = f"{cursor.year}-Q{quarter}"
        if label not in quarters:
            quarters.append(label)
        cursor = month_add(cursor, 3)
    return quarters


def print_summary(summary: FixtureSummary) -> None:
    print("VALIDATION PASSED")
    print(
        f"employees={summary.employee_count} departments={summary.department_count} "
        f"history_rows={summary.history_count}"
    )
    print(
        f"employee_statuses=active:{summary.active_count}, "
        f"inactive:{summary.inactive_count}"
    )
    print(f"attrition_rate={summary.attrition_rate:.1%}")
    print(
        "event_types="
        + ", ".join(
            f"{event_type}:{count}"
            for event_type, count in sorted(summary.event_counts.items())
        )
    )
    print(
        "quarter_terminations="
        + ", ".join(
            f"{quarter}:{count}"
            for quarter, count in sorted(summary.quarter_terminations.items())
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate and validate a synthetic HR DataHarness workspace fixture.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to write CSVs and notes.md. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--employee-count",
        type=int,
        default=DEFAULT_EMPLOYEE_COUNT,
        help=f"Number of employee rows to generate. Default: {DEFAULT_EMPLOYEE_COUNT}",
    )
    parser.add_argument(
        "--attrition-rate",
        type=float,
        default=DEFAULT_ATTRITION_RATE,
        help=f"Target inactive employee share. Default: {DEFAULT_ATTRITION_RATE}",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Deterministic random seed. Default: {DEFAULT_SEED}",
    )
    parser.add_argument(
        "--history-start",
        type=parse_date,
        default=DEFAULT_HISTORY_START,
        help=f"Start date for non-hire history events. Default: {DEFAULT_HISTORY_START}",
    )
    parser.add_argument(
        "--history-end",
        type=parse_date,
        default=DEFAULT_HISTORY_END,
        help=f"End date for non-hire history events. Default: {DEFAULT_HISTORY_END}",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate existing files in --output-dir without regenerating them.",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> GenerationConfig:
    if args.employee_count <= 0:
        raise SystemExit("--employee-count must be greater than zero")
    if not (0 <= args.attrition_rate < 1):
        raise SystemExit("--attrition-rate must be >= 0 and < 1")
    if args.history_start >= args.history_end:
        raise SystemExit("--history-start must be before --history-end")
    return GenerationConfig(
        output_dir=args.output_dir,
        employee_count=args.employee_count,
        attrition_rate=args.attrition_rate,
        seed=args.seed,
        history_start=args.history_start,
        history_end=args.history_end,
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    config = config_from_args(args)
    try:
        if args.validate_only:
            summary = validate_fixture(config.output_dir, config)
        else:
            summary = generate_fixture(config)
    except FixtureValidationError as exc:
        print(exc)
        return 1
    print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
