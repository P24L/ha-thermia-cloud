# Contributing

Thanks for helping. This is an unofficial integration for the Thermia Online cloud; the cloud API is undocumented, so real-world data from other heat pump models is the most valuable contribution.

## Before you start

- Read `docs/WORKING-RULES.md` (working rules) and `docs/ROADMAP.md` (what is planned). Design lives in `docs/`.
- Code, comments, docs, commit messages and issues are in English. User-visible strings go through `translations/en.json` and `translations/cs.json`.
- **Never write to a real heat pump while developing or testing.** Live scripts are read-only by default. Heating registers can freeze a house.

## Development setup

```bash
uv venv --python 3.14 && source .venv/bin/activate
uv pip install -r requirements_test.txt
pytest -q
ruff check . && ruff format --check .
```

Details: `docs/DEVELOPMENT.md`.

## Rules for changes

- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`), small and reviewable.
- Every client change needs a fixture-based test; every catalog change needs a planner snapshot.
- `custom_components/thermia_cloud/client/` must not import `homeassistant`.
- No credentials, tokens, hostnames, installation ids, MAC addresses, addresses or e-mails in code, fixtures, logs or issues.
- Fixtures must go through `scripts/anonymize.py` before they are committed.
- Be gentle with the cloud: no faster polling than planned, backoff on 429/5xx.

## Sharing data from your pump

Use the *new model* issue template and attach the integration's diagnostics download (it is redacted). Please look through it before posting.

## License

By contributing you agree that your work is distributed under GPL-3.0-or-later.
