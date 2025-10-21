# Repository Guidelines

## Docs
- We keep all impotant docs in .agent folder and keep them updated. This is the structure:

.agent
- Tasks: PRD & implementation plan for each feature
- System: Document the current state of the system (project structure, tech stack, integration points, database schema, and core functionalities such as agent architecture, LLM layer, etc.)
- SOP: Best practices of execute certain tasks (e.g. how to add a schema migration, how to add a new page route, etc.)
- README.md: an index of all the documentations we have so people know what & where to look for things

## Project Structure & Module Organization
Place the FastAPI application under `app/`; expose the ASGI entrypoint in `app/main.py` and group routers inside `app/api/`.

## Build, Test, and Development Commands
- `python3 -m venv .venv && source .venv/bin/activate`: create and activate a local virtual environment.
- `pip install -r requirements.txt`: install runtime and tooling dependencies.
- `uvicorn app.main:app --reload`: run the FastAPI server with live reload for local development.
- `pytest`: execute the full test suite; use `pytest tests/api -k ranking` for targeted runs.
- `ruff check app tests` and `black app tests`: lint and format code before committing.

## Coding Style & Naming Conventions
Adopt Black’s defaults (4-space indentation, 88-character lines) and keep imports sorted via Ruff. Modules and packages use snake_case (`app/services/candidate_ranker.py`); classes stay in PascalCase, while functions, async endpoints, and fixtures remain snake_case. Preference async FastAPI route handlers and type hints for request/response bodies, tool payloads, and OpenAI client wrappers. Co-locate configuration constants in `app/core/settings.py`, keeping environment lookups centralized.

## Security & Configuration Tips
Never commit secrets; load environment variables from `.env` and update `.env.example` when adding settings like `OPENAI_API_KEY` or vector index IDs. Validate configuration through `app/core/settings.py` so missing or malformed values fail fast. Rotate credentials used in fixtures and keep mock data devoid of PII. For external callbacks, document expected webhook URLs in `docs/architecture.md` and gate them behind authenticated endpoints.
