# Codebase Documentation Generator with Drift Detection

A Django + JavaScript web application that analyzes Python codebases, auto-generates documentation using Google's Gemini AI, and detects when code has drifted from its documentation on subsequent analysis runs.

## Distinctiveness and Complexity

### Why This Project is Distinct

This project is **not a social network** and **not an e-commerce site**. It is a **code analysis and documentation tool** with the following unique characteristics:

1. **AST-Based Static Analysis**: Uses Python's built-in `ast` module to parse Python source code, extracting modules, classes, and functions with full signature analysis and source hashing.

2. **LLM Integration for Documentation**: Integrates with Google's Gemini AI API to automatically generate Google-style docstrings for undocumented code.

3. **Temporal Drift Detection**: Implements a sophisticated algorithm that compares snapshots over time to detect four types of documentation drift:
   - **Stale Documentation**: Code changed but documentation wasn't updated
   - **New Undocumented Code**: New entities added without documentation
   - **Orphaned Documentation**: Documented code that was removed
   - **Signature Changes**: Function/method signatures that changed

4. **Intelligent Documentation Copying**: Avoids redundant LLM calls by copying documentation forward for unchanged code, conserving API quota and processing time.

### Why This Project is Complex

1. **Multi-Model Relational Database Design**:
   - `Repository` → `Snapshot` (one-to-many)
   - `Snapshot` → `CodeEntity` (one-to-many with self-referential parent relationships)
   - `DriftFlag` → multiple ForeignKeys to track relationships across snapshots
   - Unique constraints and indexes for performance

2. **Micro-Batch Architecture**:
   - Designed to work within undocumented platform timeout constraints
   - Client-side orchestration with multi-phase pipeline
   - Batch processing with configurable sizes (10 files for parsing, 5 entities for doc generation)

3. **Algorithmic Complexity**:
   - Source code hashing with normalization (formatting-independent change detection)
   - Qualified name matching across snapshots for drift detection
   - Differential documentation strategy (copy vs. regenerate decision logic)

4. **Production-Grade Error Handling**:
   - Rate limit handling with exponential backoff for Gemini API
   - Model fallback (gemini-3.6-flash → gemini-3.5-flash)
   - Graceful degradation on parse failures

5. **State Machine Implementation**:
   - Snapshot status progression: pending → parsing → generating_docs → detecting_drift → complete
   - Client-side orchestration coordinating multiple backend endpoints

## File Structure

```
Capstone/
├── manage.py                      # Django management script
├── requirements.txt               # Python dependencies
├── runtime.txt                    # Python version for deployment
├── pytest.ini                     # Pytest configuration
├── .env.example                   # Environment variable template
├── .gitignore                     # Git ignore rules
│
├── capstone/                      # Django project settings
│   ├── settings.py                # Main settings (DB, apps, static, media, Gemini API key)
│   ├── urls.py                    # Root URL configuration
│   ├── wsgi.py                    # WSGI entry point for deployment
│   └── asgi.py                    # ASGI entry point
│
├── accounts/                      # User authentication (minimal)
│   ├── models.py                  # User model extensions (if needed)
│   ├── views.py                   # Login, register, logout
│   └── admin.py                   # Admin registration
│
├── repositories/                  # Repository ingestion
│   ├── models.py                  # Repository model (GitHub URL or zip upload)
│   ├── views.py                   # Submit, prepare, list repositories
│   ├── urls.py                    # Repository URL patterns
│   ├── ingestion.py               # GitHub clone + zip extraction logic
│   ├── validators.py              # File count, URL, upload validation
│   └── admin.py                   # Admin panel for repositories
│
├── analysis/                      # Core analysis engine
│   ├── models.py                  # Snapshot, CodeEntity, DriftFlag models
│   ├── views.py                   # Micro-batch endpoints (parse, generate-docs, detect-drift)
│   ├── urls.py                    # Analysis URL patterns
│   ├── parser.py                  # AST-based Python parser (standalone, testable)
│   ├── drift_detector.py          # Snapshot comparison and drift flagging
│   ├── constants.py               # Batch sizes, limits (tunable after benchmarking)
│   ├── admin.py                   # Admin for snapshots, entities, drift flags
│   └── tests/                     # Unit tests
│       ├── test_parser.py         # Parser tests with fixtures
│       ├── test_drift.py          # Drift detection tests
│       └── fixtures/              # Sample Python files for testing
│           ├── simple.py
│           ├── nested_classes.py
│           └── complex_module.py
│
├── llm/                           # LLM integration (swappable)
│   ├── base.py                    # Abstract base class for LLM providers
│   ├── gemini.py                  # Gemini API client with retry logic
│   ├── prompts.py                 # Google-style docstring prompt templates
│   └── tests.py                   # LLM integration tests (mocked)
│
├── templates/                     # HTML templates
│   ├── base.html                  # Base template with Tailwind CSS CDN
│   ├── accounts/                  # Login, register templates
│   ├── repositories/
│   │   ├── submit.html            # Repository submission form
│   │   └── list.html              # User's repositories list
│   └── analysis/
│       ├── status.html            # Analysis progress with orchestrator
│       ├── browser.html           # Documentation browser
│       └── drift.html             # Drift dashboard
│
└── static/                        # Static files
    └── css/
        └── custom.css             # Additional styles (minimal)
```

## How It Works

### Phase 1: Repository Submission
User submits a GitHub repository URL. The system validates the URL and creates a `Repository` and initial `Snapshot` record.

### Phase 2: Preparation (Clone & Validate)
- Shallow clone (depth=1) from GitHub for speed
- Validate Python file count against limits (default: 100 files max)
- Store temporary path for processing

### Phase 3: Parsing (Batch Processing)
- Parse Python files in batches of 10
- Use `ast` module to extract:
  - Module-level functions
  - Classes and their public methods
  - Function signatures with type hints
  - Existing docstrings
  - Source code hashes (SHA256 of normalized body)
- Create `CodeEntity` records in database

### Phase 4: Smart Documentation Preparation
- If this is a subsequent snapshot (not first):
  - Match entities by `qualified_name` against previous snapshot
  - For unchanged code (`source_hash` matches): Copy documentation forward
  - For changed code: Leave `generated_docstring` as NULL (will be flagged as stale)
  - For new code: Leave NULL for generation

### Phase 5: Documentation Generation (Batch Processing)
- Generate docstrings ONLY for genuinely new entities (batch size: 5)
- Call Gemini API with entity signature + source body
- Rate limit handling:
  - Exponential backoff on 429 errors (1s, 2s, 4s, 8s)
  - Model fallback (gemini-3.6-flash → gemini-3.5-flash)
- Store generated docstring with timestamp

### Phase 6: Drift Detection
- Compare current snapshot with previous snapshot
- Flag four types of drift:
  1. **Stale Doc**: `source_hash` changed but doc was copied (now outdated)
  2. **New Undocumented**: Entity exists in current but not previous
  3. **Orphaned Doc**: Entity exists in previous but not current
  4. **Signature Changed**: Function/method signature string differs
- Bulk create `DriftFlag` records

### Client-Side Orchestration
JavaScript class (`AnalysisOrchestrator`) coordinates the multi-phase pipeline:
1. Calls endpoints sequentially
2. Updates progress bar (0-100%)
3. Handles errors gracefully
4. Redirects to documentation browser on completion

## Setup Instructions

### Prerequisites
- Python 3.12
- Git
- Gemini API key (get from https://aistudio.google.com/)

### Local Development

1. **Clone the repository**:
```bash
git clone <your-repo-url>
cd Capstone
```

2. **Create virtual environment**:
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

3. **Install dependencies**:
```bash
pip install -r requirements.txt
```

4. **Set environment variables**:
```bash
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

5. **Run migrations**:
```bash
python manage.py migrate
```

6. **Create superuser**:
```bash
python manage.py createsuperuser
```

7. **Run development server**:
```bash
python manage.py runserver
```

8. **Access the application**:
- Main app: http://localhost:8000/repositories/
- Admin panel: http://localhost:8000/admin/

### Running Tests
```bash
python -m pytest
```

## Deployment to Render

### Prerequisites
- Render account (https://render.com)
- GitHub repository with this code
- Gemini API key

### Steps

1. **Create PostgreSQL database**:
   - In Render dashboard: New → PostgreSQL
   - Select Free tier
   - Note: Free tier has 30-day limit, then data is deleted

2. **Create Web Service**:
   - New → Web Service
   - Connect your GitHub repository
   - Configuration:
     - **Name**: docgen-web (or your choice)
     - **Environment**: Python 3
     - **Build Command**: `pip install -r requirements.txt && python manage.py migrate`
     - **Start Command**: `gunicorn capstone.wsgi`
     - **Instance Type**: Free

3. **Set Environment Variables**:
   - In web service settings → Environment:
     - `DJANGO_SECRET_KEY`: (auto-generate via Render)
     - `GEMINI_API_KEY`: (paste your key from Google AI Studio)
     - `PYTHON_VERSION`: 3.12.0
     - `DEBUG`: False
     - `ALLOWED_HOSTS`: your-app.onrender.com
     - `DATABASE_URL`: (auto-set by connecting Postgres database)

4. **Connect Database**:
   - In web service settings → Environment
   - Add the PostgreSQL database you created in step 1

5. **Deploy**:
   - Render will automatically deploy on git push
   - First deploy takes ~5 minutes
   - Check logs for any errors

### Important Render Notes
- **Free tier limitations**:
  - Web service spins down after 15 minutes of inactivity
  - First request after spin-down takes ~30 seconds
  - Database limited to 30 days then deleted
- **No background workers on free tier**: This is why we use micro-batch architecture with client-side orchestration

## Getting a Gemini API Key

1. Visit https://aistudio.google.com/
2. Sign in with Google account
3. Click "Get API key" → "Create API key"
4. Copy the key to your `.env` file
5. **Free tier limits**:
   - 15 requests per minute
   - 1 million tokens per day
   - Sufficient for demo-scale repos (~30 files)

## Technical Decisions

### Micro-Batch Architecture
**Problem**: Render's free-tier request timeout isn't publicly documented. Industry standard for free PaaS platforms is 30 seconds.

**Solution**: Micro-batch processing keeps every request under 15 seconds:
- Parsing: 10 files per batch (~5s per batch)
- Doc generation: 5 entities per batch (<10s worst case with retries)
- Client orchestrates sequentially

This design provides margin for any plausible timeout limit rather than risking a single long-running request.

### Documentation as a Review Gate, Not Auto-Fix
The application **deliberately does not auto-regenerate documentation** when code changes:
- **First snapshot**: All entities get LLM-generated docs
- **Subsequent snapshots**:
  - Unchanged code → docs copied forward
  - Changed code → flagged as `stale_doc` but NOT regenerated
  - New code → docs generated automatically

**Why?**
- Conserves LLM quota (only calls Gemini for new code)
- User review gate (drift flags require manual inspection)
- More complex workflow than silent batch rewrite

### Source Hashing for Change Detection
Uses SHA256 of **normalized** source body:
- Strips extraneous whitespace
- Collapses multiple newlines
- Formatting-only changes don't trigger drift flags

### Why AST over Regex?
- Robust handling of nested structures (classes within modules, methods within classes)
- Handles Python's indentation-based syntax reliably
- No fragility from edge cases

### Gemini Model Selection
Primary: `gemini-3.6-flash` (user-specified, faster)
Fallback: `gemini-3.5-flash` (stable, widely available)

Rate limit handling: exponential backoff (1s → 2s → 4s → 8s)

## Intentional Scope Limitations

These are documented as deliberate engineering decisions, not oversights:

1. **Python-only**: No JavaScript/TypeScript support (would require different AST parser)
2. **Public repos only**: No GitHub OAuth or private repo access (security/scope)
3. **Manual analysis**: No webhook triggers or CI/CD integration (deployment complexity)
4. **Best-effort static analysis**: Cannot resolve dynamic/metaprogrammed code
5. **No nested class support**: Parser extracts top-level classes and their methods, but not classes inside classes
6. **Not containerized**: Direct deployment via Render's Python buildpack (simpler for demo)

## Known Limitations

- **Temporary directory cleanup**: Cloned repos are not automatically cleaned up. For production, implement a periodic cleanup task to remove directories older than 24 hours.
- **No resume capability**: If user closes browser during analysis, they must re-submit. Analysis state is persisted but no UI for resuming.
- **Limited to small repos**: Configured for repos with <100 Python files. Larger repos may exceed free-tier timeout limits.

## Future Enhancements (Out of Scope)

- Multi-language support (requires language-specific AST parsers)
- GitHub App integration for private repos and webhook triggers
- Custom LLM fine-tuning for domain-specific documentation
- Line-level diff visualization (currently shows hash/signature changes)
- Export documentation to Markdown/HTML

## License

CS50W Capstone Project - Educational Use

## Author

CS50W Student - 2026

---

**Built with**: Django 5.1.1, Google Gemini AI, Tailwind CSS, Python 3.12
