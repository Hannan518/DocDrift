# Codebase Documentation Generator with Drift Detection

A Django + JavaScript web application that analyzes Python codebases, auto-generates documentation using Google's Gemini AI, and detects when code has drifted from its documentation on subsequent analysis runs.

## Distinctiveness and Complexity

### Why This Project is Distinct

This project is **not a social network** and **not an e-commerce site**. It is a **code analysis and documentation tool** with the following unique characteristics:

1. **AST-Based Static Analysis** — Uses Python's built-in `ast` module to parse Python source code, extracting classes, async functions, and nested method hierarchies with full signature analysis. Source hashes strip docstrings so docs-only commits never trigger false drift.

2. **LLM Integration for Documentation** — Integrates with Google's Gemini API to generate Google-style docstrings for undocumented code, with fast-fail on auth errors, retry on transient failures, and graceful handling of empty/malformed responses.

3. **Temporal Drift Detection** — Compares successive snapshots and produces four flag types: `stale_doc` (code changed), `new_undocumented` (new code with no doc), `orphaned_doc` (documented code that was removed), and `signature_changed` (public interface changed). The detector is idempotent (re-running on the same pair produces the same flags) and stores real unified diffs in each flag for direct rendering.

4. **Resume-Safe Client Orchestrator** — A small JS state machine drives a five-phase pipeline (prepare → parse → copyDocs → genDocs → drift). Each phase is restartable: a closed-tab refresh picks up where it left off without re-doing work or losing data.

### Why This Project is Complex

1. **Relational Snapshot Model**
   - `Repository` → `Snapshot` (one-to-many)
   - `Snapshot` → `CodeEntity` (one-to-many, self-referential `parent` for class→method nesting)
   - `DriftFlag` (multiple FKs to track relationships across snapshots)
   - `unique_together('owner','name')` on `Repository` — re-submitting re-uses the repo with a fresh snapshot

2. **Cursor-Based Doc Generation**
   - The LLM work-set shrinks as entities become documented; offset pagination skips entities, so a `after_id` cursor (`id__gt`) is the only correct primitive
   - Workers call the LLM only; the main thread performs a single `bulk_update` to avoid concurrent SQLite writes
   - The endpoint exposes `next_after_id` (null when exhausted) plus `remaining`, `succeeded`, `failed` so the client can bound retries

3. **Algorithmic Detail**
   - Docstring-stripped source hashing — `_unparse_without_own_docstring` removes the first `Expr(Constant(str))` before hashing
   - Qualified-name matching across snapshots (`module.Class.method`) for drift detection
   - Signature extraction with positional-only marker, `*args` before kw-only, `**kwargs` last, `self/cls` removal, `async def` prefix

4. **Production-Grade Error Handling**
   - Shared `parse_json_body` helper — every POST view returns 400 on malformed JSON
   - `LLMConfigError` fast-fail for missing/invalid API keys (no per-entity silent swallow)
   - `response.text` None guard, exponential backoff (1s → 2s → 4s), model fallback
   - Zero-file validation in `prepare_analysis` rejects empty repos with a clear error
   - SQLite WAL + `init_command` for concurrent read safety

5. **State Machine**
   - Snapshot status: `pending → ready_to_parse → parsing → parsing_complete → generating_docs → docs_complete → detecting_drift → complete` (or `failed` at any step)
   - `error_message` stored on the snapshot; surfaced in the UI and on the JSON progress endpoint

## File Structure

```
Capstone/
├── manage.py                      # Django management script
├── requirements.txt               # Python dependencies
├── pytest.ini                     # Pytest configuration (collects all app tests)
├── .env.example                   # Environment variable template
│
├── capstone/                      # Django project
│   ├── settings.py                # DB, apps, static, Gemini key, SQLite WAL
│   ├── urls.py                    # Root URL configuration
│   ├── utils.py                   # parse_json_body() shared helper
│   └── tests.py                   # Tests for the shared helper
│
├── accounts/                      # User authentication
│   ├── views.py                   # landing, register
│   ├── tests.py                   # Landing + registration tests
│   └── admin.py
│
├── repositories/                  # Repository ingestion
│   ├── models.py                  # Repository model (owner + name unique)
│   ├── views.py                   # submit, prepare, list, detail, reanalyze, delete
│   ├── urls.py
│   ├── ingestion.py               # GitHub clone + temp-dir cleanup
│   ├── validators.py              # File count, URL validation
│   └── tests.py
│
├── analysis/                      # Core analysis engine
│   ├── models.py                  # Snapshot, CodeEntity, DriftFlag
│   ├── views.py                   # Micro-batch endpoints (parse, prepare-docs,
│   │                              #   generate-docs-batch, detect-drift, progress)
│   ├── urls.py
│   ├── parser.py                  # AST-based Python parser (async, signature, hash)
│   ├── drift_detector.py          # Idempotent snapshot comparison with unified diffs
│   ├── constants.py               # PARSING_BATCH_SIZE, DOC_GEN_BATCH_SIZE
│   └── tests/
│       ├── test_parser.py         # Async, docstring-excluded hashes, signatures
│       ├── test_drift.py          # Idempotency, flag conditions, unified diff
│       ├── test_docgen_cursor.py  # Cursor pagination, termination, no skips
│       └── fixtures/              # simple.py, nested_classes.py, complex_module.py
│
├── llm/                           # LLM integration (swappable)
│   ├── base.py                    # LLMConfigError
│   ├── gemini.py                  # Gemini client (retry, fallback, auth fail-fast)
│   ├── prompts.py                 # Google-style docstring templates
│   └── tests.py                   # LLM tests (mocked)
│
├── templates/                     # HTML templates
│   ├── base.html                  # Theme toggle, nav, toast container
│   ├── landing.html               # Marketing landing page (logged-out only)
│   ├── registration/              # Branded login + register
│   ├── repositories/              # list, submit, detail
│   └── analysis/                  # status, browser, drift
│
└── static/                        # Static files
    ├── css/main.css               # Design system (light + dark, all components)
    └── js/
        ├── app.js                 # CSRF, fetch, toast, theme toggle, mobile nav
        └── pages/                 # list, submit, detail, status, browser, drift
```

## How It Works

### Phase 1: Repository Submission
User submits a public GitHub URL on `/repositories/submit/`. The system validates the URL, looks up the repo by `(owner, name)`, and creates a new `Snapshot` (or reuses the existing `Repository`).

### Phase 2: Preparation (Clone & Validate)
- Shallow clone (`depth=1`) into a temp directory
- Validate Python file count; reject zero-file repos with a clear error
- Capture the `commit_hash` so each snapshot is immutable
- The temp directory is cleaned up after drift detection completes

### Phase 3: Parsing (Batch Processing)
- Parse Python files in batches of 10 (`PARSING_BATCH_SIZE`)
- For each file, the AST parser produces one `CodeEntity` per class, per public method, and per module-level function (including `async def`)
- Signatures preserve positional-only markers, `*args` before kw-only, `**kwargs` last; `self`/`cls` is removed from method signatures
- Source hashes are computed on the docstring-stripped body so docs-only edits never trigger drift
- After each batch, class→method `parent` links are wired via a single `bulk_update` keyed on `qualified_name`

### Phase 4: Smart Documentation Preparation
- If a previous complete snapshot exists, `prepare_docs` copies generated docs forward for entities whose `source_hash` is unchanged
- Changed or new code is left for the LLM
- `doc_source` is set to `existing` for entities that already have a docstring in the source — these are also counted as documented

### Phase 5: Documentation Generation (Cursor-Batched)
- The work-set is `entities.filter(generated_docstring__isnull=True, existing_docstring__isnull=True)` — a snapshot, not a filter on the original queryset
- The client sends `after_id`; the server returns up to `DOC_GEN_BATCH_SIZE` entities with `id > after_id` plus `next_after_id` (null when exhausted)
- 10 worker threads call the LLM; results are written back from the request thread in one `bulk_update`
- A `LLMConfigError` (bad API key) aborts the whole batch with a clear `error_message`
- The client loops until `next_after_id` is null, then attempts up to a small number of retry rounds for any remaining failures

### Phase 6: Drift Detection
- Compare the current snapshot to the most recent prior `complete` snapshot by `timestamp`
- For each `qualified_name`:
  - new + undocumented → `new_undocumented`
  - hash changed → `stale_doc` (with full unified diff in `detail`)
  - signature changed → `signature_changed` (with full unified diff in `detail`)
  - removed + previously documented → `orphaned_doc`
- Idempotent: prior flags for the current snapshot are deleted first
- The diff text is stored in `DriftFlag.detail['unified_diff']` and rendered by the JS on demand (no client-side diffing required)

### Client-Side Orchestrator
`static/js/pages/status.js` runs an explicit phase state machine (`prepare → parse → copyDocs → genDocs → drift`) keyed off the snapshot's persisted status. The browser never relies on offset pagination or in-memory queues, and a refresh of the status page resumes the right phase.

## Setup Instructions

### Prerequisites
- Python 3.12+
- Git
- Gemini API key (https://aistudio.google.com/)

### Local Development

```bash
# 1. Clone
git clone <your-repo-url>
cd Capstone

# 2. Virtualenv
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 3. Dependencies
pip install -r requirements.txt

# 4. Environment
cp .env.example .env
# Edit .env and set GEMINI_API_KEY
# (DJANGO_SECRET_KEY defaults to a dev value when unset)

# 5. Migrate
python manage.py migrate

# 6. (Optional) Admin
python manage.py createsuperuser

# 7. Run
python manage.py runserver
```

- Marketing landing: http://localhost:8000/
- App: http://localhost:8000/repositories/
- Admin: http://localhost:8000/admin/

### Running Tests
```bash
python -m pytest
```
The test runner uses pytest-django with `pytest.ini` and collects all app-level tests.

## Design Decisions

### Cursor over Offset
Offset pagination on a shrinking queryset is the classic source of "infinite loop" bugs. `after_id` is stable: even as entities leave the work-set, the cursor always points to the next unseen id.

### Docstring-Stripped Hashes
A docs-only commit (e.g. someone improving an existing docstring) should not flag every method as `stale_doc`. Hashing the docstring-stripped body means only real source changes count.

### Idempotent Drift
Re-running the pipeline for any reason should not pile up duplicate flags. Deleting prior flags for the current snapshot before creating new ones makes the detector safe to call repeatedly.

### Server-Side Diffs
Diffs are computed once with `difflib.unified_diff` and stored on the flag, so the browser never needs a diff library and the diff is part of the persisted record.

### Worker DB Discipline
SQLite serializes writes. The doc-gen workers only call the LLM and return their result tuple; a single main-thread `bulk_update` writes them all.

### UI: Light + Dark Toggle
- CSS variables only (`[data-theme="dark"]` selector + `prefers-color-scheme` fallback)
- No CSS framework runtime — a single hand-crafted stylesheet in `static/css/main.css`
- Theme persisted in `localStorage`; toggle is in the nav bar

## Intentional Scope Limitations

1. **Python-only** — AST is language-specific; other languages would need a different parser.
2. **Public repos only** — No GitHub OAuth for private repos.
3. **No nested-class extraction** — Top-level classes and their public methods are parsed; classes inside classes are not recursed into.
4. **No webhook triggers** — Analysis is started from the UI.
5. **Best-effort static analysis** — Dynamic / metaprogrammed code is not resolved.

## Known Limitations

- **Repo size**: Configured for repos with <100 Python files (raises a clear validation error otherwise).
- **Re-submitting the same repo** triggers a fresh snapshot and a new analysis run.

## Future Enhancements (Out of Scope)

- Multi-language AST parsers
- GitHub App for private repos + webhooks on push
- Line-level annotations in the diff view
- Export to Markdown / HTML

## License

CS50W Capstone Project — Educational Use
