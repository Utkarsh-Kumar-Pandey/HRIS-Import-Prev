# HRIS Import Preview

A small Django exercise that accepts an HRIS CSV upload, analyzes it entirely in memory, and displays an import preview. There are no database writes, no authentication, and no JavaScript framework.

## Structure

```text
hris_import_preview/
├── manage.py
├── requirements.txt
├── sample_hris.csv
├── config/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
└── importer/
    ├── core.py
    ├── views.py
    ├── urls.py
    ├── templates/importer/
    │   ├── upload.html
    │   └── results.html
    └── tests/test_core.py
```

`importer/core.py` contains plain Python logic with no Django imports. Parsing, identity validation, manager resolution, direct-report counting, and cycle detection are separate functions so they can be tested and explained independently. `views.py` only handles the uploaded file, converts core-level `UploadError`s into user-facing messages, and passes one `AnalysisResult` object to the template.

## Analysis result shape

`AnalysisResult` keeps the output coherent instead of spreading unrelated values across the Django view. It contains:

- `total_rows`
- `accepted_employees`
- `errors`
- `root_employees`
- `manager_direct_report_counts`
- `cyclic_employees`
- `accepted_count` as a convenience property

## Setup and run

Requires Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py runserver
```

Open `http://127.0.0.1:8000/` and upload `sample_hris.csv` from the project root.

No migrations are required because this exercise does not use a database.

## Run the tests

```bash
python manage.py test
```

The focused core tests cover duplicate identity exclusion, manager-reference conflicts, cycle membership versus a non-cyclic tail, quoted commas/BOM handling, and missing-header upload errors.

## Implementation notes

### 1. CSV parsing and normalization

The parser uses Python's `csv.DictReader`, so quoted fields containing commas are handled correctly. The uploaded bytes are decoded with `utf-8-sig`, which accepts normal UTF-8 and also removes an optional BOM.

Every field is trimmed. `email` and `manager_email` are lowercased. Employee and manager IDs remain case-sensitive.

### 2. Identity validation

Identity validation happens before any hierarchy work. Two `Counter`s count non-empty employee IDs and normalized emails. A row is excluded if its ID/email is missing or if either appears more than once in the file.

This makes duplicate detection O(n), and it ensures invalid identity rows never enter manager indexes or graph analysis.

### 3. Manager resolution

Accepted employees are indexed once by ID and normalized email. Each manager lookup is therefore expected O(1).

The four manager-input cases are handled explicitly:

- both blank: root
- ID only: resolve by employee ID
- email only: resolve by normalized email
- both: both references must resolve to the same employee

A manager-resolution error does not remove the employee from the accepted set. It simply prevents an edge from being added, and that employee is not treated as a root.

### 4. Direct reports

Every successfully resolved `employee -> manager` edge contributes one count to that manager. Only managers with a positive count appear in the results.

### 5. Cycle detection

The reporting graph has at most one outgoing edge per employee because each employee can resolve to at most one manager. Cycle detection walks each manager chain with three states:

- `0`: unseen
- `1`: currently on the active traversal path
- `2`: fully processed

For each new start node, the algorithm stores the current path and the index where each node entered that path. If following managers reaches a state-1 node that is also in the current path, only the suffix beginning at that node is a cycle. This is why a tail such as `D -> A -> B -> C -> A` leaves `D` non-cyclic while marking `A/B/C`.

Every employee is processed at most once after becoming fully processed, so the work is O(V + E) and avoids Python recursion-depth problems for files around 100,000 employees.

## Assumptions

- Extra CSV columns are allowed; all required columns must still exist.
- Surrounding whitespace in header names is tolerated.
- A completely blank upload, a header-only CSV, missing required headers, invalid UTF-8, duplicate headers, or a row with more fields than the header is treated as a malformed upload and shown as a user-facing error.
- Self-management through either a matching `manager_id` or a manager email that resolves back to the same employee is treated as `employee manages themselves`.
- Row numbers refer to physical CSV rows with the header as row 1, so the first data row is row 2.
- Results preserve accepted employee file order where practical; manager-count order follows the first resolved report encountered for each manager.

## Known limitations

- The upload is read fully into memory. That is appropriate for this exercise, but a production import pipeline might stream, impose upload-size limits, or use background processing.
- Error messages are intentionally concise and are not localized.
- There is no schema validation beyond the requested identity/manager rules and basic malformed-CSV checks.
- The UI is deliberately plain because styling was not part of the exercise.
