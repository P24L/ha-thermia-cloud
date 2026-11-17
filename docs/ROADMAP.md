# Roadmap and checklist

Tick items with `- [x]`. IDs (`P3.4`) are referenced from the other docs. Phases are ordered, but items inside a phase can be parallel.

**Status (2026-11-17):** design phase done and reviewed, all decisions accepted. Next: Phase 0/1 (see `docs/WORKING-RULES.md`).
**Legend:** 🧪 spike (find out) · 🔒 needs the maintainer's explicit OK (heating/real HA/public action)

Related: `DECISIONS.md` · `ARCHITECTURE.md` · `API-NOTES.md` · `CATALOG.md` · `UI-DESIGN.md` · `DEVELOPMENT.md` · `RELEASE.md`

---

## Phase 0 — Spikes: close the unknowns

- [x] P0.1 🧪 Does the B2C token response contain a `refresh_token` for this tenant/scope (`openid offline_access` + client id)? How long is it valid? → **yes, valid 24 h, rotated on every use, works** (2026-11-17, `API-NOTES.md` §2) → auth design: stored refresh token, password re-login as fallback. Sliding vs fixed 24 h still open (P0.3 probe)
- [ ] P0.2 🧪 Measure real access-token lifetime (long-running probe, 6 h): when does the first `401` appear? *(probe running since 2026-11-17; server says 3600 s)*
- [ ] P0.3 🧪 Measure the gateway's upload cadence from `timeStamp` deltas per register for 24 h → choose default interval and "data fresh" threshold *(probe running since 2026-11-17, also exercises the refresh-token chain for 24 h)*
- [ ] P0.4 🧪 Is `registerIndex` unique per installation across more dumps? (fixtures from other profiles/families) → confirm D10 *(unique in profile 1005; needs other families)*
- [ ] P0.5 🧪 Visibility-condition grammar: collect all conditions from more dumps; confirm operators (`=`, `!=`, `<`, `<=`, `>`, `>=`, `AND`, `OR`, parentheses?) *(profile 1005 only has `>=`, `>`, `=`, `AND`; parser should support the full set)*
- [ ] P0.6 🧪 How does a login fail when Thermia requires accepting new terms? Collect from upstream issues; define detection → `PolicyAcceptanceError`
- [ ] P0.7 🧪 `modifier` meaning table (8/12/1/16/0/…) and decoding of `StatusFlagsTextInd` vs `StatusFlags` vs `MultipleStatusFlags` *(modifier table done for profile 1005; status-flag variants need other families)*
- [ ] P0.8 🧪🔒 Write semantics: latency until read-back after a write; behaviour when the device is offline (`queueId`). Test by writing the **current value** of a harmless register
- [ ] P0.9 🧪 `REG_PID` ("Heat demand"): unit and range; is it gone for good?
- [ ] P0.10 🧪 Meaning of group `visibility` 1/2/3/null (role level?) *(not derivable from one dump; `null` = empty technical groups, 1–3 do not predict data; ignore in v0.1)*
- [ ] P0.11 🧪 Is the WebSocket (`isWebSocketEnabled`) enabled for other regions/accounts? Is `api-prod.thermia.com` reachable with a mobile-app token? (optional)
- [x] P0.13 Remaining decisions D3, D5, D7, D9 and the override-editor question confirmed by the maintainer (2026-11-17); editor is **not** in v0.1

## Phase 1 — Repository bootstrap

- [x] P1.0 Design docs + anonymized fixtures (`tests/fixtures/itec_profile_1005/`)
- [x] P1.1 `git init` and first commit of the docs (`.gitignore` is already in place)
- [x] P1.2 Review `LICENSE` (GPL-3.0, copied from upstream), `NOTICE.md` credits wording, `hacs.json`, `CHANGELOG.md` (reviewed 2026-11-17: no changes needed; `LICENSE` carries the unmodified GPL text, `NOTICE.md` credits klejejs and states independence, `hacs.json` min HA 2026.10.0)
- [x] P1.3 `pyproject.toml` (ruff, mypy, pytest config), `requirements_test.txt`, `.pre-commit-config.yaml`
- [x] P1.4 `uv venv --python 3.14` works, `pytest` runs an empty suite
- [x] P1.5 CI: `validate.yml` (hassfest + HACS action), `tests.yml`
- [x] P1.6 `CONTRIBUTING.md`, `SECURITY.md`, issue templates (bug / new model / feature)
- [x] P1.7 🔒 Create the **public** GitHub repo `P24L/ha-thermia-cloud` (decision D12), push, set description + topics (`home-assistant`, `hacs`, `homeassistant-integration`, `thermia`, `heat-pump`)
- [ ] P1.8 Draft icon (own generic heat-pump drawing, not the Thermia logo)
- [ ] P1.9 🔒 Heads-up post to `klejejs/ha-thermia-heat-pump-integration` discussions (courtesy; announce the alternative) — after P0.12

## Phase 2 — Client library (`custom_components/thermia_cloud/client/`)

- [ ] P2.1 `errors.py` typed exceptions
- [ ] P2.2 `config.py` — `/api/configuration` discovery + cache (apiBaseUrl, authority, clientId, scopes, `isWebSocketEnabled`)
- [ ] P2.3 `auth.py` — async B2C PKCE flow **written independently** from `API-NOTES.md` §2 (D2: no upstream code copied); private cookie-jar session, proactive refresh, generation-checked single-flight lock; `AuthError` only for definitive bad credentials, `LoginFlowError` otherwise (refresh-token use per P0.1)
- [ ] P2.4 `http.py` — timeouts, `401 → re-auth once → retry once`, bounded immediate retries with jitter (longer waits are the coordinator's job), redacted logging
- [ ] P2.5 `models.py` — `Installation`, `Group`, `RegisterSpec`, `RegisterValue`, `Snapshot`
- [ ] P2.6 `api.py` — installations, groups, group registers, history registers, status, languages, localization
- [ ] P2.7 `scripts/anonymize.py` — diagnostics/dump → fixture folder (strips ids, names, MAC, address, tokens)
- [ ] P2.8 `api.write_register()` — validation (numbers vs min/max/step, enums vs **visible** `valueNames`, `isReadOnly`), per-installation lock, `RegisterWriteError`; semantics refined by P0.8
- [ ] P2.9 `sources.py` — `ValueSource` protocol + `PollingSource` (needed-groups selection)
- [ ] P2.10 Client unit tests with fixtures (auth happy/bad password/401 retry/429; empty-group = `[]` is not an error)
- [ ] P2.11 `scripts/live_smoke.py` (read-only, env credentials; prints the discovered specs now, the entity plan once P3.4 exists)
- [ ] P2.12 Anonymized fixtures for the auth HTML/JSON (csrf/transId placeholders), `installationsInfo`, `installations/{id}`, status and write responses; extend `scripts/anonymize.py`

## Phase 3 — Visibility, catalog, planner, labels

- [ ] P3.1 `client/visibility.py` — parser + evaluator; **structural vs value-based** split; unresolved reference = visible (recorded); same-group name resolution; table-driven tests from `history_registers.json`
- [ ] P3.2 `catalog/schema.py` + `loader.py` (YAML, executor): `GROUP/NAME` → `NAME` lookup (plain `NAME` rejected when the name occurs in several groups), per-register `device:`, `translation_key`, default device `main`
- [ ] P3.3 `catalog/catalog.yaml` — initial content: the 26 iTec registers (incl. decisions: `REG_ACTIVATE_CIRC1` = select Curve/Constant, `risk: heating`; both `REG_OPERATIONMODE` as selects; `REG_OPER_DATA_DISTR_CIR1` on circuit 1; status flags enabled) + registers known from upstream (`REG_BRINE_*`, `REG_RETURN_LINE`, `REG_COOL_*`, pool, buffer tank, …)
- [ ] P3.4 `planner.py` — pure `EntityPlan` builder (generic rules §4, *visible wins* for enums, risk flags, defaults, stale-register rule, name collision pass) + `syrupy` snapshot for the iTec fixture
- [ ] P3.5 Unit resolution (catalog → modifier map → en-US bracket parse through a fixed unit table → none) + tests
- [ ] P3.6 `scripts/sync_localization.py` + bundled `i18n/*.json` for all 16 cultures (+ `_meta.json`)
- [ ] P3.7 `LabelResolver` (order in `CATALOG.md` §5.2, language *Auto*) + tests (cs-CZ fallbacks, bracket stripping, curated names)
- [ ] P3.8 Status-flag decoding (equality vs bitmask) + tests with `COMP_STATUS_ITEC`

## Phase 4 — HA integration core (read-only)

- [ ] P4.1 `manifest.json`, `const.py`; review the existing `hacs.json` (name *Thermia Cloud (unofficial)*, min HA 2026.10); brand images in `custom_components/thermia_cloud/brand/` (`icon.png` 256×256, `icon@2x.png`)
- [ ] P4.2 Config flow: user → create; entry `unique_id` = token `sub`; errors per `UI-DESIGN.md` §1; installation selection in options
- [ ] P4.3 Reauth flow
- [ ] P4.4 Reconfigure flow
- [ ] P4.5 Coordinator per installation: explicit `config_entry`, `always_update=False`, discovery cache in a `Store`, needed groups from the entity registry (verify HA's reload-on-enable behaviour), `ConfigEntryAuthFailed` / `UpdateFailed(retry_after)`
- [ ] P4.6 Base entity, devices, child devices (`via_device`, `DeviceInfo(translation_key)`), `runtime_data`, dynamic devices + `async_remove_config_entry_device`
- [ ] P4.7 `sensor.py` (generic + timestamp + enum)
- [ ] P4.8 `binary_sensor.py` (status flags)
- [ ] P4.9 `diagnostics.py` (redaction + plan + visibility results)
- [ ] P4.10 `translations/en.json`, `translations/cs.json`
- [ ] P4.11 HA integration tests (setup/unload, entities from fixture, auth failure → reauth, multi-installation)
- [ ] P4.12 **Bronze acceptance criteria enforced here, not at the end:** `test-before-configure`, `test-before-setup`, `unique-config-entry`, `config-flow-test-coverage`, `runtime-data`, `has-entity-name`, `entity-unique-id`, `appropriate-polling`, `entity-unavailable` (one log line down / one up)

## Phase 5 — Writing

- [ ] P5.4 **Do first:** Read-only mode (option + error message) — no writable build may exist without the kill switch
- [ ] P5.1 `number.py` (limits from the cloud, step rounding)
- [ ] P5.2 `select.py` (visible `valueNames`, localized)
- [ ] P5.3 `switch.py` (two-value enumerations, hot water)
- [ ] P5.5 Per-installation write lock, `pending_value` attribute, fast-poll read-back; **no debounce**, errors raised to the caller, queued writes are not errors (D6)
- [ ] P5.6 `thermia_cloud.set_register` service + `services.yaml` (registered in `async_setup`, targets entry/device, same policy as entities)
- [ ] P5.7 Write tests (validation, read-only, mismatch, offline device)
- [ ] P5.8 Safety review of `risk` flags in the catalog (every writable register classified)

## Phase 6 — Options, repairs, UX

- [ ] P6.1 Options flow: General (interval, read-only, timeout, debug attributes)
- [ ] P6.2 Options flow: Installations & registers (installation selection, show hidden, expose unknown)
- [ ] P6.3 *(moved to P10.8 — not in v0.1)*
- [ ] P6.4 Names: **Refresh names** button, *Label language* option (Auto / explicit culture), stored labels. **No weekly auto-refresh** (D4)
- [ ] P6.5 Repairs: `policy_acceptance_required` (not fixable), `register_vanished`, `discovery_empty`. No `auth_failed` Repair — reauth covers it
- [ ] P6.6 Buttons on the device page: Refresh names, Rediscover registers
- [ ] P6.7 Tests for options/repairs/overrides

## Phase 7 — Polish

- [ ] P7.1 Optional composite `water_heater` for hot water (convenience; generic entities stay)
- [ ] P7.2 *(moved to P10.7)*
- [ ] P7.3 Quality-scale **bronze** final audit (the criteria are already enforced in P4.12)
- [ ] P7.4 Quality-scale **silver**: reauth, parallel updates, `config-entry-unloading`, `integration-owner`, `docs-configuration-parameters`, `docs-installation-parameters`, `log-when-unavailable`, integration-module coverage > 95 %
- [ ] P7.5 Final README with screenshots/GIF (see README outline)
- [ ] P7.6 Czech translation review; optional `README.cs.md`
- [ ] P7.7 Final icon, dashboard example (Mushroom) in README
- [ ] P7.8 Performance check: request rate matches plan; no blocking calls in the event loop

## Phase 8 — Validate on the maintainer's production setup 🔒

- [ ] P8.1 Dev HA on the Mac (`hass -c dev-config`), integration set up with Read-only mode ON
- [ ] P8.2 `live_smoke.py` against the real account; compare discovered plan with fixture
- [ ] P8.3 🔒 Backup + deploy dev build to the real HA (Path A) — Stage A *observe ≥ 7 days* (checklist in `DEVELOPMENT.md` §4.4)
- [ ] P8.4 Stage A results recorded (value comparison, request rate, token expiry, restart survival)
- [ ] P8.5 🔒 Stage B: enable writes for the main heating curve only; verify in the Thermia app
- [ ] P8.6 Dual-curve sync (main + circuit 1 from one slider) re-created as an **HA automation/script** on the new number entities (no integration feature needed)
- [ ] P8.7 🔒 Stage C: migrate scripts/automations that wrote to the cloud themselves (e.g. AppDaemon scripts) to the new entities; keep the old script disabled for a week, then remove
- [ ] P8.8 🔒 Stage D: inventory + re-point references to the old integration's entities (automations, scenes, dashboards), then remove the old integration
- [ ] P8.9 Record the migration in the maintainer's own change log and notes (kept outside this repository)

## Phase 9 — Publish

- [x] P9.1 Marketplace publishing rules read (<https://www.home-assistant.io/integrations/marketplace/>, 2026-11-17) — summarized in `RELEASE.md` §1. Still open: how a repo enters the default catalog (follow the HACS rules)
- [ ] P9.2 Brand images are in `custom_components/thermia_cloud/brand/` (per HA developer docs, since HA 2026.3: `icon.png` 256×256, `icon@2x.png` 512×512, optional `logo*.png`, `dark_*`); our own drawing, not the Thermia logo; verify the Marketplace shows it
- [ ] P9.3 🔒 Public-repo polish: social preview image, final topics, issue templates live, CI green
- [ ] P9.4 `v0.1.0` as a regular GitHub release (beta in the notes; the Marketplace hides pre-releases by default); manifest version matches the tag
- [ ] P9.5 🔒 Install on the maintainer's HA via Marketplace *Add from link* (no restart expected); update path tested with `v0.1.1`
- [ ] P9.6 🔒 Announce — **only after P0.12**: courtesy post to upstream, HA community forum thread
- [ ] P9.7 Collect community diagnostics → fixtures → catalog entries (issue label `new-model`)
- [ ] P9.8 `v1.0.0` when bronze+ is green, ≥ 2 other users confirmed, no open data-loss/auth bugs
- [ ] P9.9 🔒 PR to `hacs/default` (checklist in `RELEASE.md` §5)

## Phase 10 — Later / stretch

- [ ] P10.1 Extract `client/` as PyPI package `thermia-cloud`
- [ ] P10.2 Other profile families (Genesis, Atlas, Diplomat, ATEC): fixtures + catalog
- [ ] P10.3 Ask core maintainers about acceptance of reverse-engineered cloud APIs; decide on core submission
- [ ] P10.4 Import DataHistory into long-term statistics (backfill)
- [ ] P10.5 Explore the `api-prod.thermia.com` API
- [ ] P10.6 Document interplay with local projects (ESPHome iTec, Modbus Genesis) in README
- [ ] P10.7 `WebSocketSource` (JSON-RPC push) if/when Thermia turns `isWebSocketEnabled` on; fall back to polling
- [ ] P10.8 "Unmapped registers" editor → `options.overrides` (cost estimate in `UI-DESIGN.md` §4); build only if users of other model families ask for it
