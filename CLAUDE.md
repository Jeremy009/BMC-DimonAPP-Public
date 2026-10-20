# DimonAPP V3.0

Internal web app for Brussels Monkeys Climbing ASBL (BMC). Workers declare climbing-gym activities; the app checks contracts and qualifications, sends Dimona declarations to the RSZ/ONSS, tracks legal limits, produces the monthly payment file and the yearly fiscal fiches 281.27.

## Source of truth

- `docs/FDS.md` is the functional specification. Read the relevant sections before you change anything.
- Every requirement has an ID (R1.1 to R19.1, Appendix A of the FDS). Build only what the FDS asks for; if something is unclear or seems wrong, stop and ask instead of guessing.
- `docs/openapi_dimona_v2.yaml` is the official RSZ specification of the Dimona REST service. The Dimona client (`src/dimonapp/rsz_dimona.py`) was ported from DimonAPP V2 (R8.5); the V2 code is no longer kept, and the RSZ key lives outside the repository in `~/Projects/DimonAPP-Secrets/`.

## Stack (decided, do not change without asking)

- Python, managed with **uv**; everything in `pyproject.toml`; `uv.lock` committed.
- **Streamlit** UI, tab based. Code in `src/dimonapp/`, tests in `tests/`.
- **SQLAlchemy 2.0** (typed ORM) + **psycopg 3**; **Alembic** migrations, applied at container start.
- PostgreSQL (Cloud SQL in GCP, a Docker container locally).
- Google sign-in via Streamlit's built-in OIDC (`st.login`, `st.user`, `st.logout`, needs Authlib). Local accounts: username + password hashed with **Argon2** (argon2-cffi).
- Docker, one image for the three environments: TEST (no Dimona call), ACC (RSZ test service), PROD (live RSZ service). GCP: Cloud Run (max 1 instance), Cloud SQL, Cloud Storage, Secret Manager, region europe-west1.
- Tests: **pytest**; database tests use **testcontainers** PostgreSQL; the Dimona API is always mocked in tests.

## Commands

- `make test`: run the full test suite. It must pass before any change counts as done.
- `make run`: start the app locally with settings from `.env`.
- `make lint`: run `ruff format` and `ruff check --fix`. Ruff is configured in `pyproject.toml` with line length 100 and single quotes.
- Add other targets only when useful (for example `make migrate`, `make db`).

## Way of working

Every feature, fix or requirement change follows the same loop. Never commit directly to `main`.

1. **Branch.** Start from an up-to-date `main` on a new branch named `claude/<feature>` (for example `claude/r8-dimona-client`). One branch per unit of work; keep it small enough to review.
2. **Build.** Implement only what the FDS asks for in that unit, following the Python style below.
3. **Version.** Raise the version in `src/dimonapp/__init__.py` (the only place, R18.8) once for every pull request, before opening it: the next release candidate number until the first release (`3.0.0rc1`, `3.0.0rc2`, ...; the betas `3.0.0b6` to `3.0.0b32` came before), semantic versioning after that. Review commits on the same pull request keep its version.
4. **Check.** `make lint` leaves no changes and no warnings, and `make test` passes. Fix failures; do not skip, weaken or delete tests to get green.
5. **Pull request.** Push the branch and open a PR against `main`. The description lists the version, the requirement IDs covered, what was built, how it was tested, and anything left open or deviating from the FDS.
6. **Stop and ask for review.** Never merge a PR, never push to `main`, never force-push a branch under review. The user reviews and merges. Address review comments with new commits on the same branch.

Start the next unit only after the previous PR is merged, unless the user says otherwise.

## Rules that must never be broken

1. **French interface.** Every label, message, error, month name and number format is in French (1 234,50 €, 2,5 h, dates DD/MM/YYYY). The FDS (section 3.4) has the English-to-French label table. Code, comments, tests and commit messages are in English.
2. **No secrets in code, image or repo.** Everything comes from environment variables: `.env` locally (git-ignored, template in `.env.example`), Secret Manager in GCP. Keys and certificates live in a folder outside the repository, never in it, not even git-ignored. `.streamlit/secrets.toml` is generated at start-up from environment variables and is never committed.
3. **Activities are immutable.** Once declared, only the cancellation marker can change, plus the Dimona fields when an admin resolves a pending declaration. The rate, model, worker type and amount are copied onto the activity at declaration time.
4. **Never assume a Dimona outcome.** What is shown and stored is always based on the real API response or its absence (2-minute timeout leads to "pending").
5. **Never block on legal limits.** The compliance engine warns on the admin dashboard; it does not refuse declarations. Limits come only from the `yearly_limits` table.
6. **Personal data.** National register numbers and IBANs live only in the `workers` table and never appear in logs. Passwords are stored only as Argon2 hashes and are never displayed.
7. **Simplicity first.** Readable, testable code over clever abstractions. Small modules, plain functions for business rules, so they can be tested without Streamlit.

## Working conventions

- Put business rules (submission gate, compensation, validity of authorisations, compliance engine, status ladder) in plain Python modules under `src/dimonapp/`, separate from Streamlit pages, and test them directly.
- Wrap external systems behind small interfaces with a fake implementation for tests and local work: Dimona client, file storage (local folder vs Cloud Storage), clock (for "today").
- Reference requirement IDs in test names or docstrings (for example `test_r8_4_volunteer_activity_registered_without_dimona`) and in commit messages.
- With every change, update `docs/TRACEABILITY.md`: requirement ID, where it is implemented, which test covers it.
- If a requirement changes during the build, update `docs/FDS.md` first, then the code.

## Python style

### Design

- Prefer functional code: small, explicit, composable functions and short pipelines over classes and abstractions.
- Introduce a class only when a framework requires it (SQLAlchemy ORM models) or for the small interfaces around external systems listed above.
- Structured application data that is not a database table lives in Pydantic `BaseModel` subclasses, not `dataclass`. Models hold validation and schema, not behaviour.
- Write the minimal code that solves the task. Add defensive error handling at external boundaries (Dimona API, database, storage, user input), not speculatively elsewhere.

### Formatting

- `ruff format` with single quotes. 100 characters is a hard line-length limit.
- One statement or expression per line. Keep calls, definitions, decorators, returns and loop headers on a single line whenever they fit in 100 characters and stay readable.
- When the formatter wants to wrap, simplify first: extract nested calls and long attribute accesses into meaningfully named intermediate variables. Readability matters more than minimising the number of variables.
- A log message that fits on one line goes straight into the logging call as an f-string. Build it in a variable first only when it needs more than that; do not nest formatting calls inside the logging call.
- Keep keyword arguments when simplifying; never switch to positional arguments to shorten a line.
- When multiple lines are unavoidable: exactly one argument, parameter or item per line, a trailing comma after the last one, and the closing delimiter on its own line.
- No trailing comma in a single-line call or definition (Ruff reads it as a request to expand).

```python
# Avoid
logger.info(
    format_log(
        'Dimona declared.',
        activity_id=activity.id,
        status=response.status,
    )
)

# Prefer
activity_id = activity.id
status = response.status
logger.info(f'Dimona declared for activity {activity_id}: {status}.')
```

### Imports

- Imports at the top of the file, one package per line. Never `from x import *`.
- Standard abbreviations only (for example `import sqlalchemy as sa`).

### Types and docstrings

- Type annotations on every function parameter and return value, helpers and tests' fixtures included.
- Built-in generics (`list`, `dict`, `tuple`), never `List`, `Dict`, `Tuple` from `typing`. Use `Optional[T]` for nullable values.
- Every function has a docstring: a one-line summary, optionally followed by a short note on what it does and why it exists. Never use `Args:` / `Returns:` / `Raises:` sections.

### Naming

- PEP 8: `do_something`, `my_variable`, `MyClass`, `MY_CONSTANT`, `my_module.py`.
- Function names use a specific active verb. Counts are `n_<something>` (for example `n_activities`).
- No data types in names (`workers`, not `workers_list` or `worker_dict`).

### Code quality

- Keyword arguments everywhere.
- `pathlib` for all file paths, never `os.path` or string manipulation.
- f-strings for simple formatting; `str.join()` instead of `+` in loops.
- Avoid deep nesting: bail out early with `return`, `continue` or `break`.
- Keep comprehensions simple, with a single `for` clause.
- Never use mutable default arguments. Compare to `None` with `is` / `is not`. Never write `== True` or `== False`.
- Iterate directly (`for key in my_dict`), use `enumerate()` for indices and `in` / `not in` for membership.
- Merge dictionaries with `{**a, **b}` or `a.update(b)`; never the `|` operator.
- Context managers for files, connections and anything else that needs cleanup.
- Catch specific exceptions; no bare or catch-all `except`.

### Logging and comments

- A module that logs defines `logger = logging.getLogger(__name__)` at module level; a module that logs nothing needs no logger. Never call `logging.getLogger()` inside a function. Log the execution flow so behaviour is easy to trace (never personal data, see rule 6).
- Short block comments split the major steps of longer functions (`# Check the submission gate`, `# Send the declaration`). Comments explain why and organise flow; they do not narrate obvious code.
- `# TODO:` for actionable future work, `# NOTE:` for decisions awaiting follow-up. No commented-out code.

### Tests

- Tests are isolated from each other: no shared state, temporary paths for files.
- `pytest.raises(ValueError)` without a `match` argument, unless the error text is itself part of the contract (for example a French message shown to the user).
