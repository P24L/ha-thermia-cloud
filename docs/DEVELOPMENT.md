# Development, testing and deployment to a real Home Assistant

Facts as of 2026-11-17: the maintainer's Mac has `uv`, a system Python newer than 3.14, Node, git and `gh`; **no Docker**. The reference production setup is a Home Assistant OS box running `core-2026.11.1` (Python 3.14.10), reachable remotely over a VPN only, with the Terminal & SSH add-on. Machine-specific details (hosts, key paths, entity names) live in the git-ignored `private/` folder and local notes.

## 1. Local environment (Mac)

HA needs Python ≥ 3.14 — use `uv` to get its own interpreter, don't touch the system Python.

```bash
cd ~/dev/ha-thermia-cloud
uv venv --python 3.14
source .venv/bin/activate
uv pip install -r requirements_test.txt     # pytest-homeassistant-custom-component, ruff, mypy
pytest -q
```

`requirements_test.txt` pins `pytest-homeassistant-custom-component`; that package pins the matching `homeassistant` (at the time of writing `0.13.375` ⇒ `homeassistant==2026.10.4`, i.e. the newest version we can unit-test against until the plugin catches up with 2026.11 — see D7).

Tooling: `ruff` (lint + format), `mypy --strict` for `client/` and `catalog/`, `pre-commit` (install with `uv tool install pre-commit`).

## 2. Test layers

| Layer | Tool | What |
|---|---|---|
| Client unit | `pytest` + local fake aiohttp server (`tests/client/conftest.py`; `aioresponses` 0.7.9 does not work with aiohttp 3.14) | auth flow against recorded HTML/JSON, 401 → re-auth → retry, 429/5xx backoff, typed errors, write validation, `ValueSource` fallbacks |
| Visibility DSL | `pytest` (table-driven) | every condition seen in `history_registers.json` + malformed input |
| Catalog | `pytest` | schema valid; every key used exists in some fixture or is flagged "family-only" |
| Planner | `pytest` + golden JSON files (`tests/catalog/golden/`, `UPDATE_GOLDEN=1` to accept a change) | `tests/fixtures/itec_profile_1005/` → exact entity set (platform, key, unit, default_enabled, device) |
| Labels | `pytest` | resolution order, bracket-unit stripping, culture fallback (fixture `localization_cs-CZ.excerpt.json`) |
| HA integration | `pytest-homeassistant-custom-component` | config flow (success, bad auth, policy page, multi-installation, reauth, reconfigure, options), setup/unload, entities, services, repairs, diagnostics snapshot |
| Live smoke (manual) | `scripts/live_smoke.py` | **read-only** run against the real cloud with env credentials; prints discovered plan; never writes |
| Static | `hassfest`, `hacs/action`, `ruff`, `mypy` | CI |

Coverage targets: `client/`, `catalog/`, planner ≥ 90 %; rest ≥ 80 %.

### Fixtures

`tests/fixtures/<family>_profile_<id>/` — already present: `itec_profile_1005/` (23 group files, profile groups, history registers, cs-CZ excerpt). Extracted from a real pump and **hand-checked** (no e-mail, MAC, address, installation id or name; `installationId` is set to 0). New fixtures come only from the anonymizer (`scripts/anonymize.py`).

## 3. Running a throw-away HA on the Mac

```bash
mkdir -p dev-config/custom_components
ln -s ../../custom_components/thermia_cloud dev-config/custom_components/thermia_cloud
hass -c dev-config            # http://localhost:8123 → onboarding → add integration "Thermia Cloud"
```

- It talks to the **real Thermia cloud** with your account → turn on **Read-only mode** in the options right after setup.
- Iterate here (restart `hass` after Python changes). Nothing here touches the production HA.
- `dev-config/` is git-ignored.

## 4. Deploying to the real HA

> Production rules: take a **backup first**; installing/removing integrations, restarting HA and anything that can affect the heating need **explicit confirmation** from the person responsible for that house.

### 4.1 Preflight (every time)

- [ ] Create an HA backup (UI *Settings → System → Backups*, or via the HA MCP `ha_manage_backup`) and note its id.
- [ ] `ha core check` passes (over SSH).
- [ ] Nobody is relying on the heating right now (remote house, frost forecast?). Prefer daytime, mild weather.
- [ ] Read-only mode will be ON for the first start.

### 4.2 Path A — before the repository is public (development builds)

```bash
# Over your VPN with the SSH add-on; set these in your shell, never in the repo
KEY=~/.ssh/<your_key>; HA=root@<ha-host>
find custom_components/thermia_cloud -name __pycache__ -prune -exec rm -rf {} +
scp -i $KEY -r custom_components/thermia_cloud $HA:/config/custom_components/
ssh -i $KEY $HA 'ha core check && echo OK'          # then, after confirmation:
ssh -i $KEY $HA 'ha core restart'
```
The SSH add-on's Alpine has no `rsync` by default, hence `scp`. `scripts/deploy_dev.sh` wraps these steps and **stops before the restart** unless `--restart` is given. First load of a new custom component and every code change need a restart; options/config changes only need an entry reload.

### 4.3 Path B — public repository (normal path, no restart for the first install)

*Settings → Marketplace → ⋮ → **Add from link** → `P24L/ha-thermia-cloud` → Download → the setup flow opens without a restart* (2026.11 behavior; updates still need a restart). Shareable link: `https://my.home-assistant.io/redirect/hacs_repository/?owner=P24L&repository=ha-thermia-cloud&category=integration` (verify the redirect still targets the Marketplace). To test a branch/pre-release, pick it in the download dialog.

### 4.4 Rollout plan on a production HA

Used for the maintainer's own installation; the same shape works for anyone replacing another Thermia integration. (Maintainer-specific inventories are kept outside the repository.)

**Stage A — observe (≥ 7 days).** New integration next to the old one (different domain), Read-only mode ON for the observation period.
- [ ] Add the integration; confirm entity count and the default-enabled set match the plan.
- [ ] Compare against the old entities: outdoor, supply, desired supply, hot water, compressor/aux hours, status flags. Differences ≤ one polling interval.
- [ ] HA log clean (no auth errors, no warning spam); request rate ≈ plan (architecture §3.2).
- [ ] Re-login survives token expiry (watch a > 3 h window) and an HA restart.
- [ ] A vanished register is handled (entity unavailable + Repair).

**Stage B — writes, one register at a time.** Read-only OFF after explicit approval; start with the main heating curve.
- [ ] Change by ±1 → value confirmed in the Thermia app and read back by the integration.
- [ ] Verify nothing else changed (e.g. the circuit-1 curve; mirroring both curves is done with an HA automation, roadmap P8.6).

**Stage C — migrate scripts and automations** that wrote to the cloud themselves (AppDaemon scripts, custom clients): re-point them to the new entities, keep the old script disabled for a week before deleting it (rollback = re-enable).

**Stage D — retire the old integration.**
- [ ] Inventory references to the old entities (automations, scenes, dashboards) with `ha_search`/the entity usage view.
- [ ] Re-point or replace them and test each one.
- [ ] Backup, then remove the old integration (explicit confirmation).

Rollback at any stage: remove the new config entry (the old integration keeps working); restore the backup if configuration was touched.

## 5. Quality bar (self-assessment against the HA quality scale)

Bronze (enforced from Phase 4, P4.12): config flow with tests, unique ids, `has_entity_name`, `runtime_data`, appropriate polling, entity unavailability on failure (one log line down/up), documented setup/removal, branding. Silver (P7.4): reauth flow, parallel updates, `config-entry-unloading`, `integration-owner`, `docs-configuration-parameters`, `docs-installation-parameters`, `log-when-unavailable`, integration-module test coverage > 95 %, action exceptions raised properly. Gold (nice): diagnostics, entity/icon translations (`translation_key`), repairs, reconfigure, documented devices.

## 6. Conventions

- Code, comments, commit messages, docs: English. User-visible Czech via `translations/cs.json`.
- No `device_id` in services; `entity_id` only.
- Commits: conventional style (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
- Each client change comes with a fixture-based test; each catalog change with a planner snapshot.
