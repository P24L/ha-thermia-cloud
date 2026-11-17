# Working rules

Guidance for everyone working in this repository.

## What this is

**Thermia Cloud** — a Home Assistant custom integration (`custom_components/thermia_cloud`) that talks to the Thermia Online / MyThermia cloud, discovers a heat pump's registers from the cloud's own description and exposes them as entities (read **and** write), with several circuits, several installations and localized names. Unofficial; GPL-3.0-or-later. Public repository: `P24L/ha-thermia-cloud`.

Status: design done, code not started. **Read first, in this order:** `docs/ROADMAP.md` (what to do, tick boxes as you go) → `docs/DECISIONS.md` → `docs/ARCHITECTURE.md` → `docs/API-NOTES.md` → `docs/CATALOG.md` → `docs/UI-DESIGN.md` → `docs/DEVELOPMENT.md` → `docs/RELEASE.md`.

## Working rules

- **Roadmap is the source of truth.** When a task is done, tick it in `docs/ROADMAP.md` in the same change. When you learn a fact about the cloud API, record it in `docs/API-NOTES.md` with its confidence level; when a decision changes, update `docs/DECISIONS.md`.
- **Language:** code, comments, docs, commit messages, issue text in English. User-visible strings go through `translations/en.json` and `translations/cs.json`.
- **Layering:** `custom_components/thermia_cloud/client/` must **not** import `homeassistant`. The planner is a pure function. HA glue stays thin.
- **Independent auth implementation:** `client/auth.py` is written from `docs/API-NOTES.md` §2 — do not copy or port code from the `klejejs/*` projects (decision D2).
- **Home Assistant conventions:** `ConfigEntry.runtime_data` (not `hass.data`), `DataUpdateCoordinator`, `has_entity_name=True`, `entity_id` in services (never `device_id`; the `set_register` power-user service targets a config entry/device — a documented exception), typed errors (`ConfigEntryAuthFailed`, `UpdateFailed`, `HomeAssistantError` with translation keys), async only (no blocking calls in the event loop).
- **Python 3.14**, `ruff` (lint+format), `mypy --strict` on `client/` and `catalog/`, tests with `pytest`; every client change needs a fixture-based test, every catalog change an updated planner golden file.
- **Commits:** conventional (`feat:`, `fix:`, `docs:`, `test:`, `chore:`), small and reviewable.

## Safety and privacy (non-negotiable)

- **Never write to a real heat pump or a real Home Assistant without explicit approval from the maintainer** in the current conversation. Heating registers can freeze a house. Roadmap items marked 🔒 always need that approval.
- **Live access is read-only by default** (`scripts/live_smoke.py`). Credentials come only from environment variables (`THERMIA_USERNAME`, `THERMIA_PASSWORD`); never read a credentials file into the conversation, never print or log tokens/passwords, never commit them.
- **The repository is public.** Do not put hostnames, key paths, entity/automation names of a private HA, installation ids, MAC addresses, addresses or e-mails into tracked files. Private notes go to the git-ignored local notes and `private/`.
- Test fixtures must go through `scripts/anonymize.py` before they are committed.
- The cloud API is undocumented and unofficial: be gentle (no polling faster than the plan allows, no hammering on failures, backoff on 429/5xx).

## Common commands

```bash
uv venv --python 3.14 && source .venv/bin/activate
uv pip install -r requirements_test.txt
pytest -q                    # unit + HA integration tests
ruff check . && ruff format --check .
mypy custom_components/thermia_cloud/client custom_components/thermia_cloud/catalog
hass -c dev-config           # throw-away HA on the Mac (see docs/DEVELOPMENT.md §3)
```

(The files behind these commands are created in roadmap Phase 1.)
