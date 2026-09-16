# Repository Guidelines

## Project Structure & Module Organization

ZeroWall combines a Python defense loop and Next.js operator UI. `core/` contains agents, safe source transforms, deployment logic, telemetry, and training code in matching subdirectories. The simulated FastAPI target is in `apps/target-fastapi/`. Triton models and clients live in `inference/`; `dashboard/` contains Python dashboards and `frontend/` the Next.js app. Repository tests are in `tests/`, with target contract tests beside the target app. Treat `artifacts/deploy/`, `telemetry_data/`, and generated training outputs as runtime data, not hand-edited source.

## Build, Test, and Development Commands

- `python -m venv .venv && source .venv/bin/activate` creates and activates the Python environment.
- `pip install -r requirements.core.txt` installs core dependencies.
- `pytest -q` runs all Python unit, transform, target, and integration tests.
- `bash scripts/run_target.sh` starts the managed local FastAPI target.
- `bash scripts/run_demo.sh` executes the end-to-end hardening demonstration.
- `docker compose up -d` starts the full DGX-oriented service stack.
- `cd frontend && npm install && npm run dev` starts the dashboard on port 3000.
- `cd frontend && npm run build` performs the production type/build check; `npm run lint` runs Next.js linting.

## Coding Style & Naming Conventions

Use four-space indentation in Python, `snake_case` for functions/modules, and `PascalCase` for classes. Prefer type hints, `pathlib.Path`, structured models, and module loggers over ad hoc printing. TypeScript uses two-space indentation, `camelCase` values, and `PascalCase` React components. No repository-wide autoformatter is configured, so preserve nearby style and keep changes focused.

## Testing Guidelines

Pytest discovers `test_*.py` files as configured in `pytest.ini`. Add regression tests for every behavior change, especially transforms, exploit blocking, live deployment gates, and rollback. Tests must remain deterministic, local, and non-destructive. Run `pytest -q` before opening a pull request; UI changes should also pass `npm run build`.

## Commit & Pull Request Guidelines

Recent history favors concise imperative subjects with prefixes such as `feat:`, `fix:`, and `docs:`. Keep commits single-purpose. Pull requests should explain the user-visible outcome, note test commands and results, link relevant issues, and include screenshots for dashboard changes. Call out configuration, model, or deployment behavior changes explicitly.

## Security & Configuration

Never commit `.env`, credentials, private keys, or machine-specific paths. Copy settings from `.env.example`. All bundled attacks target only the simulated local application; do not point replay tooling at external systems or expose demo services to untrusted networks. Follow `SECURITY.md` for vulnerability reporting.
