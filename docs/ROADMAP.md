# Roadmap and checklist

Tick items with `- [x]`. IDs (`P3.4`) are referenced from the other docs. Phases are ordered, but items inside a phase can be parallel.

**Status (2026-11-17):** design phase done and reviewed, all decisions accepted. Next: Phase 0/1 (see `docs/WORKING-RULES.md`).
**Legend:** 🧪 spike (find out) · 🔒 needs the maintainer's explicit OK (heating/real HA/public action)

Related: `DECISIONS.md` · `ARCHITECTURE.md` · `API-NOTES.md` · `CATALOG.md` · `UI-DESIGN.md` · `DEVELOPMENT.md` · `RELEASE.md`

---

## Phase 0 — Spikes: close the unknowns

- [x] P0.1 🧪 Does the B2C token response contain a `refresh_token` for this tenant/scope (`openid offline_access` + client id)? How long is it valid? → **yes, valid 24 h, rotated on every use, works** (2026-11-17, `API-NOTES.md` §2) → auth design: stored refresh token, password re-login as fallback. Sliding vs fixed 24 h still open (P0.3 probe)
- [x] P0.2 🧪 Measure real access-token lifetime (long-running probe, 6 h): when does the first `401` appear? *(2026-11-18: token refused between 3608 and 3908 s, i.e. about 1 h; the integration renews proactively)*
- [x] P0.3 🧪 Measure the gateway's upload cadence from `timeStamp` deltas per register for 24 h → choose default interval and "data fresh" threshold *(2026-11-18: per-register timestamps change only on a new value (fast temperatures 1–10 min, hours ~1.8 h, outdoor up to 27 h); default 60 s stays (D9); see API-NOTES section 8)*
- [ ] P0.4 🧪 Is `registerIndex` unique per installation across more dumps? (fixtures from other profiles/families) → confirm D10 *(unique in profile 1005; needs other families)* *(2026-11-17: also unique within each of the six community dumps (ATEC, Diplomat ×2, iTec 2024, NCP ×2; older cloud); the *same* index means different registers in different families, so never key a catalog entry by index)*
- [ ] P0.5 🧪 Visibility-condition grammar: collect all conditions from more dumps; confirm operators (`=`, `!=`, `<`, `<=`, `>`, `>=`, `AND`, `OR`, parentheses?) *(profile 1005 only has `>=`, `>`, `=`, `AND`; parser should support the full set)*
- [ ] P0.6 🧪 How does a login fail when Thermia requires accepting new terms? Collect from upstream issues; define detection → `PolicyAcceptanceError`
- [ ] P0.7 🧪 `modifier` meaning table (8/12/1/16/0/…) and decoding of `StatusFlagsTextInd` vs `StatusFlags` vs `MultipleStatusFlags` *(modifier table done for profile 1005; status-flag variants need other families)* *(2026-11-17: the web-app rule is `(value & flag) == flag` for `StatusFlagsTextInd`/`MultipleStatusFlags`, equality for `StatusFlags`, only `visible:true` flags (from the upstream scripts); matches our implementation)*
- [ ] P0.8 🧪🔒 Write semantics: latency until read-back after a write; behaviour when the device is offline (`queueId`). Test by writing the **current value** of a harmless register *(plan: `docs/WRITE-TEST.md`)* *(2026-11-17: first live write of the main curve +1 verified — empty 200 body, read-back after 3.1 s, nothing else changed; offline/rejection behaviour and the circuit-1 curve still to do)*
- [x] P0.9 🧪 `REG_PID` ("Heat demand"): unit and range; is it gone for good? *(2026-11-18: not returned by the live cloud (gone for good since the 2026-09 migration); in the 2024 iTec dump it was `Integer`, read-only, `modifier` 4, value 50, no limits, group OPERATIONAL_STATUS — probably a percentage, but unverified, so the catalog entry stays unitless and disabled)*
- [x] P0.10 🧪 Meaning of group `visibility` 1/2/3/null (role level?) *(not derivable from one dump; `null` = empty technical groups, 1–3 do not predict data; ignore in v0.1)* *(2026-11-18: across the six community dumps `null` groups are all empty (4/4); visibility 1 appears on 34 non-empty and 72 empty groups, 2 on 1/1, 3 on 3/0 — no predictive meaning, ignored)*
- [ ] P0.11 🧪 Is the WebSocket (`isWebSocketEnabled`) enabled for other regions/accounts? Is `api-prod.thermia.com` reachable with a mobile-app token? (optional)
- [x] P0.12 Thermia terms of use reviewed by the maintainer (2026-11-17); label snapshots (D4) and public announcement are cleared
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
- [x] P1.8 Draft icon (own generic heat-pump drawing, not the Thermia logo) *(final: generated artwork, 256 and 512 px in `brand/`; no brand marks)*
- [ ] P1.9 🔒 Heads-up post to `klejejs/ha-thermia-heat-pump-integration` discussions (courtesy; announce the alternative) — after P0.12

## Phase 2 — Client library (`custom_components/thermia_cloud/client/`)

- [x] P2.1 `errors.py` typed exceptions
- [x] P2.2 `config.py` — `/api/configuration` discovery + cache (apiBaseUrl, authority, clientId, scopes, `isWebSocketEnabled`)
- [x] P2.3 `auth.py` — async B2C PKCE flow **written independently** from `API-NOTES.md` §2 (D2: no upstream code copied); private cookie-jar session, proactive refresh, generation-checked single-flight lock; `AuthError` only for definitive bad credentials, `LoginFlowError` otherwise (refresh-token use per P0.1)
- [x] P2.4 `http.py` — timeouts, `401 → re-auth once → retry once`, bounded immediate retries with jitter (longer waits are the coordinator's job), redacted logging
- [x] P2.5 `models.py` — `Installation`, `Group`, `RegisterSpec`, `RegisterValue`, `Snapshot`
- [x] P2.6 `api.py` — installations, groups, group registers, history registers, status, languages, localization 
- [x] P2.7 `scripts/anonymize.py` — diagnostics/dump → fixture folder (strips ids, names, MAC, address, tokens)
- [x] P2.8 `api.write_register()` — validation (numbers vs min/max/step, enums vs **visible** `valueNames`, `isReadOnly`), per-installation lock, `RegisterWriteError`; semantics refined by P0.8 *(validated and serialized; tested against a fake server and fakes only — the real cloud's write response and latency are still unknown (P0.8 🔒))*
- [x] P2.9 `sources.py` — `ValueSource` protocol + `PollingSource` (needed-groups selection)
- [ ] P2.10 Client unit tests with fixtures (auth happy/bad password/401 retry/429; empty-group = `[]` is not an error) *(auth, http, models, api read-side covered, 20 tests against a local fake server; write tests follow P2.8)*
- [x] P2.11 `scripts/live_smoke.py` (read-only, env credentials; prints the discovered specs now, the entity plan once P3.4 exists)
- [ ] P2.12 Anonymized fixtures for the auth HTML/JSON (csrf/transId placeholders), `installationsInfo`, `installations/{id}`, status and write responses; extend `scripts/anonymize.py` *(done: installationsInfo, installation, status in `tests/fixtures/api/`, hand-built from key names; auth placeholders live in `tests/client/conftest.py`; missing: write responses (P0.8))*

## Phase 3 — Visibility, catalog, planner, labels

- [x] P3.1 `client/visibility.py` — parser + evaluator; **structural vs value-based** split; unresolved reference = visible (recorded); same-group name resolution; table-driven tests from `history_registers.json`
- [x] P3.2 `catalog/schema.py` + `loader.py` (YAML, executor): `GROUP/NAME` → `NAME` lookup (plain `NAME` rejected when the name occurs in several groups), per-register `device:`, `translation_key`, default device `main`
- [ ] P3.3 `catalog/catalog.yaml` — initial content: the 26 iTec registers (incl. decisions: `REG_ACTIVATE_CIRC1` = select Curve/Constant, `risk: heating`; both `REG_OPERATIONMODE` as selects; `REG_OPER_DATA_DISTR_CIR1` on circuit 1; status flags enabled) + registers known from upstream (`REG_BRINE_*`, `REG_RETURN_LINE`, `REG_COOL_*`, pool, buffer tank, …) *(done: all 26 iTec registers curated and tested; still open: the upstream-known registers (`REG_BRINE_*`, `REG_RETURN_LINE`, cooling, pool, buffer tank), whose exact names/units must be verified before they go in)*
- [x] P3.4 `planner.py` — pure `EntityPlan` builder (generic rules §4, *visible wins* for enums, risk flags, defaults, stale-register rule, name collision pass) + golden JSON file for the iTec fixture
- [x] P3.5 Unit resolution (catalog → modifier map → en-US bracket parse through a fixed unit table → none) + tests
- [x] P3.6 `scripts/sync_localization.py` + bundled `i18n/*.json` for all 16 cultures (+ `_meta.json`)
- [x] P3.7 `LabelResolver` (order in `CATALOG.md` §5.2, language *Auto*) + tests (cs-CZ fallbacks, bracket stripping, curated names)
- [x] P3.8 Status-flag decoding (equality vs bitmask) + tests with `COMP_STATUS_ITEC`

## Phase 4 — HA integration core (read-only)

- [x] P4.1 `manifest.json`, `const.py`; review the existing `hacs.json` (name *Thermia Cloud (unofficial)*, min HA 2026.10); brand images in `custom_components/thermia_cloud/brand/` (`icon.png` 256×256, `icon@2x.png`) *(done; icon in `brand/`)*
- [x] P4.2 Config flow: user → create; entry `unique_id` = token `sub`; errors per `UI-DESIGN.md` §1; installation selection in options *(user → installations → create; installation selection in the options flow comes with P6.2)*
- [x] P4.3 Reauth flow
- [x] P4.4 Reconfigure flow
- [x] P4.5 Coordinator per installation: explicit `config_entry`, `always_update=False`, discovery cache in a `Store`, needed groups from the entity registry (verify HA's reload-on-enable behaviour), `ConfigEntryAuthFailed` / `UpdateFailed(retry_after)` *(needed groups follow the entity registry; verified: enabling an entity makes HA reload the entry ~30 s later, disabling does not)*
- [x] P4.6 Base entity, devices, child devices (`via_device`, `DeviceInfo(translation_key)`), `runtime_data`, dynamic devices + `async_remove_config_entry_device` *(child devices via `via_device_id`; removable only when no longer in the plan; devices for new groups appear at the next setup/rediscovery)*
- [x] P4.7 `sensor.py` (generic + timestamp + enum)
- [x] P4.8 `binary_sensor.py` (status flags)
- [x] P4.9 `diagnostics.py` (redaction + plan + visibility results)
- [x] P4.10 `translations/en.json`, `translations/cs.json`
- [x] P4.11 HA integration tests (setup/unload, entities from fixture, auth failure → reauth, multi-installation)
- [x] P4.12 **Bronze acceptance criteria enforced here, not at the end:** `test-before-configure`, `test-before-setup`, `unique-config-entry`, `config-flow-test-coverage`, `runtime-data`, `has-entity-name`, `entity-unique-id`, `appropriate-polling`, `entity-unavailable` (one log line down / one up) *(config_flow 100 % covered; down/up logged once each, tested)*

## Phase 5 — Writing

- [x] P5.4 **Do first:** Read-only mode (option + error message) — no writable build may exist without the kill switch *(option in the options flow, blocks entities and the service; read-only is checked before any request is made)*
- [x] P5.1 `number.py` (limits from the cloud, step rounding) *(limits and step from the cloud, slider/box by step count)*
- [x] P5.2 `select.py` (visible `valueNames`, localized) *(options = visible cloud values as language-independent ids (`hot_water`, `economy`, …), states translated)*
- [x] P5.3 `switch.py` (two-value enumerations, hot water) *(hot water on/off)*
- [x] P5.5 Per-installation write lock, `pending_value` attribute, fast-poll read-back; **no debounce**, errors raised to the caller, queued writes are not errors (D6) *(per-installation lock in the client, `pending_value` attribute, 5 s fast poll for up to 30 s, give-up logged once (info when the device is offline); not yet seen against a real pump)*
- [x] P5.6 `thermia_cloud.set_register` service + `services.yaml` (registered in `async_setup`, targets entry/device, same policy as entities) *(`device_id`, `group`, `register` (name or index), `value`; same policy as entities)*
- [x] P5.7 Write tests (validation, read-only, mismatch, offline device) *(validation, read-only, mismatch/timeout, cloud rejection; offline-device behaviour is simulated (queued write), not observed)*
- [x] P5.8 Safety review of `risk` flags in the catalog (every writable register classified) *(every writable register is classified in a regression table in `tests/catalog/test_planner.py` (D6))*

## Phase 6 — Options, repairs, UX

- [x] P6.1 Options flow: General (interval, read-only, timeout, debug attributes) *(interval, read-only, timeout, debug attributes; the options menu with installations/names comes with P6.2/P6.4)*
- [x] P6.2 Options flow: Installations & registers (installation selection, show hidden, expose unknown) *(menu: General / Installations & registers / Names & language)*
- [ ] P6.3 *(moved to P10.8 — not in v0.1)*
- [x] P6.4 Names: **Refresh names** button, *Label language* option (Auto / explicit culture), stored labels. **No weekly auto-refresh** (D4) *(label language option, *Refresh names* button, stored labels in `.storage`; no automatic refresh (D4))*
- [x] P6.5 Repairs: `policy_acceptance_required` (not fixable), `register_vanished`, `discovery_empty`. No `auth_failed` Repair — reauth covers it *(`policy_acceptance_required` (raised when the client reports it; the detection itself is still P0.6), `register_vanished` (after 7 days, persisted), `discovery_empty`)*
- [x] P6.6 Buttons on the device page: Refresh names, Rediscover registers *(Refresh names, Rediscover registers (diagnostic buttons))*
- [x] P6.7 Tests for options/repairs/overrides *(options steps, names, buttons, repairs, generic sensor kinds; the overrides item does not apply (editor is P10.8))*

## Phase 7 — Polish

- [ ] P7.1 Optional composite `water_heater` for hot water (convenience; generic entities stay) *(optional; not started — a hot-water setpoint register is unknown, so a composite entity would add little)*
- [ ] P7.2 *(moved to P10.7)*
- [x] P7.3 Quality-scale **bronze** final audit (the criteria are already enforced in P4.12) *(audit in `docs/QUALITY.md`)*
- [x] P7.4 Quality-scale **silver**: reauth, parallel updates, `config-entry-unloading`, `integration-owner`, `docs-configuration-parameters`, `docs-installation-parameters`, `log-when-unavailable`, integration-module coverage > 95 % *(audit in `docs/QUALITY.md`, coverage 97 %)*
- [ ] P7.5 Final README with screenshots/GIF (see README outline) *(README matches the implementation; screenshots/GIF still missing)*
- [ ] P7.6 Czech translation review; optional `README.cs.md` *(`cs.json` is machine-translated and needs a native review by the maintainer)*
- [x] P7.7 Final icon, dashboard example (Mushroom) in README *(final icon; Mushroom example is in the README)*
- [x] P7.8 Performance check: request rate matches plan; no blocking calls in the event loop *(dev HA log: 7 requests/min, no blocking-call warnings; file I/O runs in worker threads)*

## Phase 8 — Validate on the maintainer's production setup 🔒

- [ ] P8.1 Dev HA on the Mac (`hass -c dev-config`), integration set up with Read-only mode ON *(2026-11-17: dev HA on the Mac runs with the real account and only reads; Read-only mode itself does not exist yet (P5.4), the build has no write path at all. Restart survival checked: cached discovery reused, no re-login)*
- [x] P8.2 `live_smoke.py` against the real account; compare discovered plan with fixture *(2026-11-17: live read matched the fixture (26 registers, 14 history entries, 9 conditions) except two hot-water registers that vanished later in the day (API-NOTES §8); in dev HA all 11 default-enabled entities show the values `live_smoke` printed)*
- [ ] P8.3 🔒 Backup + deploy dev build to the real HA (Path A) — Stage A *observe ≥ 7 days* (checklist in `DEVELOPMENT.md` §4.4)
- [ ] P8.4 Stage A results recorded (value comparison, request rate, token expiry, restart survival)
- [ ] P8.5 🔒 Stage B: enable writes for the main heating curve only; verify in the Thermia app *(plan: `docs/WRITE-TEST.md`)* *(2026-11-17: first live write of the main curve +1 verified — empty 200 body, read-back after 3.1 s, nothing else changed; offline/rejection behaviour and the circuit-1 curve still to do)*
- [ ] P8.6 Dual-curve sync (main + circuit 1 from one slider) re-created as an **HA automation/script** on the new number entities (no integration feature needed)
- [ ] P8.7 🔒 Stage C: migrate scripts/automations that wrote to the cloud themselves (e.g. AppDaemon scripts) to the new entities; keep the old script disabled for a week, then remove
- [ ] P8.8 🔒 Stage D: inventory + re-point references to the old integration's entities (automations, scenes, dashboards), then remove the old integration
- [ ] P8.9 Record the migration in the maintainer's own change log and notes (kept outside this repository)

## Phase 9 — Publish

- [x] P9.1 Marketplace publishing rules read (<https://www.home-assistant.io/integrations/marketplace/>, 2026-11-17) — summarized in `RELEASE.md` §1. Still open: how a repo enters the default catalog (follow the HACS rules)
- [x] P9.2 Brand images are in `custom_components/thermia_cloud/brand/` (per HA developer docs, since HA 2026.3: `icon.png` 256×256, `icon@2x.png` 512×512, optional `logo*.png`, `dark_*`); our own drawing, not the Thermia logo; verify the Marketplace shows it *(final icon is in place; whether the Marketplace shows it is checked with the first install via Marketplace)*
- [x] P9.3 🔒 Public-repo polish: social preview image, final topics, issue templates live, CI green *(CI is green; social preview image still to do)*
- [x] P9.4 `v0.1.0` as a regular GitHub release (beta in the notes; the Marketplace hides pre-releases by default); manifest version matches the tag *(2026-11-18: v0.1.0 published as a regular (non-pre-release) GitHub release, beta in the notes)*
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
- [x] P10.9 Decided 2026-11-17: variant B — enabled-by-default is re-applied to entities the integration itself disabled earlier (see D6); unknown registers stay disabled. A *New registers: off / read-only / all* option remains a possible later addition
- [x] P10.10 Registers the cloud returns only in some state (circuit *Curve*/*Constant*, hot-water mode and interval while hot water is on) are *state-dependent*: catalog flag `state_dependent`; vanished registers are remembered for 30 days (discovery cache), their entities stay as `unavailable` and are back when the register returns, no rediscovery on vanishing (only on an unknown register appearing), no warning or Repair for flagged registers. *Rediscover registers* forgets the remembered ones
- [x] P10.11 Alarms and events as diagnostics: `GET /api/v1/installation/{id}/events?onlyActiveAlarms=false` (item keys `isActiveAlarm`, `eventTitle`), an *active alarm* binary sensor plus a count, polled every few minutes; do one read-only live call first to learn the response shape (found by reviewing the upstream sources) *(2026-11-18: *Alarm* (problem) and *Active alarms* (count) from the installation status; the events list itself is not read — the endpoint returned `{totalCount, items: []}` on the maintainer's pump, so its item shape is still unknown)*
- [x] P10.12 Catalog entries for other families (from the older-cloud community dumps): return/supply/outdoor/brine/tank/pool temperatures, aux-heater hours, defrost diagnostics, circuit-2 curve registers and groups, status registers of ATEC/Diplomat/NCP with their core flags. Units and defaults are educated guesses for families we cannot test; uncertain ones start disabled. Name traps (names without `REG_`, `REG_DESIRED_BUFFRER_TANK`) are covered by the entries
- [x] P10.14 Resilience checks from the upstream issue history (2026-11-17): hour counters that dip slightly are held (no false reset in the statistics), a read-only/hidden enum value is never offered as a choice, a rejected refresh is followed by exactly one login then reauth (no retry loop), one failing installation does not stop the others, a renamed installation keeps all entity ids, the write body never contains `registerIndex`. All covered by tests
- [ ] P10.15 Explore the classic API's `GET /api/v1/installations/{id}/calendarFunctions` (calendar/schedule functions such as reduced heating and hot water) read-only, and ATEC spot-price registers (hot-water start temperature, supply-line minimum): high value for price-based control; writes only with the maintainer's approval
- [x] P10.16 Fix: if the *first* load of one of several installations of an account fails at setup, the whole entry retries and the other installations wait; set up the healthy ones and retry the failing one in the background (found while testing resilience; at runtime installations are already independent) *(2026-11-18: healthy installations start at once, a failing one is retried in the background after 2 min; if all fail the entry retries as before)*
- [x] P10.13 A *data fresh* indicator when the gateway stops uploading (entities stay available with old values); decide after P0.3 *(register timestamps cannot tell this: they change only with the value, outdoor temperature can stand still for 27 h; computed registers refresh on every read. Candidate signal: `installationsInfo.lastOnline`, UTC)* *(2026-11-18: *Last contact* (timestamp from `lastOnline`, UTC) and *Online* diagnostics, re-read every 5 min; `register_timestamp` stays an attribute only)*
- [ ] P10.8 "Unmapped registers" editor → `options.overrides` (cost estimate in `UI-DESIGN.md` §4); build only if users of other model families ask for it
