from __future__ import annotations

import csv
import io
from collections import Counter
from dataclasses import dataclass, field
from typing import BinaryIO


REQUIRED_HEADERS = {
    "employee_id",
    "employee_name",
    "email",
    "manager_id",
    "manager_email",
    "department",
}


class UploadError(ValueError):
    """Raised when the uploaded file itself cannot be analyzed."""


@dataclass(frozen=True)
class ParsedRow:
    row_number: int
    employee_id: str
    employee_name: str
    email: str
    manager_id: str
    manager_email: str
    department: str


@dataclass(frozen=True)
class Employee:
    row_number: int
    employee_id: str
    employee_name: str
    email: str
    manager_id: str
    manager_email: str
    department: str


@dataclass(frozen=True)
class RowError:
    row_number: int
    message: str


@dataclass
class AnalysisResult:
    total_rows: int
    accepted_employees: list[Employee] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    root_employees: list[Employee] = field(default_factory=list)
    manager_direct_report_counts: list[tuple[Employee, int]] = field(default_factory=list)
    cyclic_employees: list[Employee] = field(default_factory=list)

    @property
    def accepted_count(self) -> int:
        return len(self.accepted_employees)


def _read_text(upload: BinaryIO | bytes) -> str:
    raw = upload if isinstance(upload, bytes) else upload.read()
    if not raw:
        raise UploadError("The uploaded file is empty.")

    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UploadError("The file must be UTF-8 encoded CSV data.") from exc


def parse_csv(upload: BinaryIO | bytes) -> list[ParsedRow]:
    """Parse and normalize CSV rows, preserving original source row numbers."""
    text = _read_text(upload)
    reader = csv.DictReader(io.StringIO(text, newline=""))

    if reader.fieldnames is None:
        raise UploadError("The CSV is missing a header row.")

    normalized_headers = [header.strip() if header is not None else "" for header in reader.fieldnames]
    if len(set(normalized_headers)) != len(normalized_headers):
        raise UploadError("The CSV contains duplicate column headers.")

    missing = REQUIRED_HEADERS - set(normalized_headers)
    if missing:
        raise UploadError("Missing required headers: " + ", ".join(sorted(missing)))

    # DictReader uses its original fieldnames, so map normalized header -> original header.
    header_lookup = dict(zip(normalized_headers, reader.fieldnames))
    rows: list[ParsedRow] = []

    for row_number, raw_row in enumerate(reader, start=2):
        if None in raw_row:
            raise UploadError(f"Row {row_number} has more fields than the header row.")

        def value(name: str) -> str:
            raw_value = raw_row.get(header_lookup[name], "")
            return (raw_value or "").strip()

        rows.append(
            ParsedRow(
                row_number=row_number,
                employee_id=value("employee_id"),
                employee_name=value("employee_name"),
                email=value("email").lower(),
                manager_id=value("manager_id"),
                manager_email=value("manager_email").lower(),
                department=value("department"),
            )
        )

    if not rows:
        raise UploadError("The CSV has a header but no data rows.")

    return rows


def validate_identities(rows: list[ParsedRow]) -> tuple[list[Employee], list[RowError]]:
    """Exclude rows with missing or duplicated employee identity fields."""
    id_counts = Counter(row.employee_id for row in rows if row.employee_id)
    email_counts = Counter(row.email for row in rows if row.email)

    accepted: list[Employee] = []
    errors: list[RowError] = []

    for row in rows:
        row_errors: list[str] = []
        if not row.employee_id:
            row_errors.append("employee_id is required")
        elif id_counts[row.employee_id] > 1:
            row_errors.append(f"duplicate employee_id: {row.employee_id}")

        if not row.email:
            row_errors.append("email is required")
        elif email_counts[row.email] > 1:
            row_errors.append(f"duplicate email: {row.email}")

        if row_errors:
            errors.extend(RowError(row.row_number, message) for message in row_errors)
            continue

        accepted.append(Employee(**row.__dict__))

    return accepted, errors


def resolve_managers(
    employees: list[Employee],
) -> tuple[dict[str, str], list[Employee], list[RowError]]:
    """Resolve employee -> manager relationships using full accepted-employee indexes."""
    by_id = {employee.employee_id: employee for employee in employees}
    by_email = {employee.email: employee for employee in employees}

    manager_by_employee_id: dict[str, str] = {}
    roots: list[Employee] = []
    errors: list[RowError] = []

    for employee in employees:
        manager_id = employee.manager_id
        manager_email = employee.manager_email

        if not manager_id and not manager_email:
            roots.append(employee)
            continue

        manager_from_id = by_id.get(manager_id) if manager_id else None
        manager_from_email = by_email.get(manager_email) if manager_email else None

        # Treat any resolved self-reference as the dedicated self-manager error,
        # including the email-only form of the same logical mistake.
        if employee.employee_id == manager_id or manager_from_email is employee:
            errors.append(RowError(employee.row_number, "employee manages themselves"))
            continue

        if manager_id and manager_email:
            if manager_from_id is None or manager_from_email is None:
                errors.append(RowError(employee.row_number, "manager not found"))
                continue
            if manager_from_id is not manager_from_email:
                errors.append(RowError(employee.row_number, "manager reference conflict"))
                continue
            manager = manager_from_id
        elif manager_id:
            if manager_from_id is None:
                errors.append(RowError(employee.row_number, "manager not found"))
                continue
            manager = manager_from_id
        else:
            if manager_from_email is None:
                errors.append(RowError(employee.row_number, "manager not found"))
                continue
            manager = manager_from_email

        if manager.employee_id == employee.employee_id:
            errors.append(RowError(employee.row_number, "employee manages themselves"))
            continue

        manager_by_employee_id[employee.employee_id] = manager.employee_id

    return manager_by_employee_id, roots, errors


def count_direct_reports(
    employees: list[Employee], manager_by_employee_id: dict[str, str]
) -> list[tuple[Employee, int]]:
    by_id = {employee.employee_id: employee for employee in employees}
    counts = Counter(manager_by_employee_id.values())
    return [(by_id[manager_id], count) for manager_id, count in counts.items()]


def find_cyclic_employees(
    employees: list[Employee], manager_by_employee_id: dict[str, str]
) -> list[Employee]:
    """Find exactly the nodes inside reporting cycles in O(V + E) time."""
    by_id = {employee.employee_id: employee for employee in employees}
    state: dict[str, int] = {employee.employee_id: 0 for employee in employees}
    # 0 = unseen, 1 = currently on a traversal path, 2 = fully processed.
    cyclic_ids: set[str] = set()

    for start in by_id:
        if state[start] != 0:
            continue

        path: list[str] = []
        path_index: dict[str, int] = {}
        current: str | None = start

        while current is not None and state[current] == 0:
            state[current] = 1
            path_index[current] = len(path)
            path.append(current)
            current = manager_by_employee_id.get(current)

        # A state-1 node is only a cycle for this traversal if it is on this path.
        # This prevents a tail employee that leads into a cycle from being marked cyclic.
        if current is not None and state[current] == 1 and current in path_index:
            cyclic_ids.update(path[path_index[current] :])

        for employee_id in path:
            state[employee_id] = 2

    return [employee for employee in employees if employee.employee_id in cyclic_ids]


def analyze_upload(upload: BinaryIO | bytes) -> AnalysisResult:
    rows = parse_csv(upload)
    employees, identity_errors = validate_identities(rows)
    manager_map, roots, manager_errors = resolve_managers(employees)

    return AnalysisResult(
        total_rows=len(rows),
        accepted_employees=employees,
        errors=identity_errors + manager_errors,
        root_employees=roots,
        manager_direct_report_counts=count_direct_reports(employees, manager_map),
        cyclic_employees=find_cyclic_employees(employees, manager_map),
    )
