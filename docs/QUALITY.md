# Quality scale self-assessment

Checked against the Home Assistant integration quality scale (2026-11-17). Custom integrations are
not scored by Home Assistant; this is our own audit, enforced by tests where marked.

## Bronze

| Rule | Status | Where |
|---|---|---|
| action-setup | ✅ | `thermia_cloud.set_register` registered in `async_setup` |
| appropriate-polling | ✅ | 60 s default, 10–600 s; ~7 requests/min on the iTec profile |
| brands | ✅ | `brand/icon.png`, `icon@2x.png` (draft drawing) |
| common-modules | ✅ | `coordinator.py`, `entity.py` |
| config-flow | ✅ | UI setup, `data_description` for every field |
| config-flow-test-coverage | ✅ | `config_flow.py` 100 % (test) |
| dependency-transparency | ✅ | no extra requirements (`manifest.json`: `requirements: []`) |
| docs-actions / high-level-description / installation-instructions / removal-instructions | ✅ | README |
| entity-event-setup | n/a | coordinator based |
| entity-unique-id | ✅ | `{installation}_{registerIndex}[_{flag}]` (D10), tested |
| has-entity-name | ✅ | `ThermiaEntity` |
| runtime-data | ✅ | `entry.runtime_data` |
| test-before-configure | ✅ | `async_probe` in the config flow |
| test-before-setup | ✅ | `ConfigEntryNotReady` / `ConfigEntryAuthFailed` |
| unique-config-entry | ✅ | `unique_id` = token `sub` |

## Silver

| Rule | Status | Where |
|---|---|---|
| action-exceptions | ✅ | `HomeAssistantError` with translation keys (`writer.py`) |
| config-entry-unloading | ✅ | `async_unload_entry` closes the client session |
| docs-configuration-parameters | ✅ | README *Configuration* |
| docs-installation-parameters | ✅ | README *Setup* |
| entity-unavailable | ✅ | register missing / hidden by condition / failed poll |
| integration-owner | ✅ | `codeowners` in the manifest |
| log-when-unavailable | ✅ | one line down, one line up (test) |
| parallel-updates | ✅ | `PARALLEL_UPDATES` in every platform |
| reauthentication-flow | ✅ | `async_step_reauth` |
| test-coverage > 95 % | ✅ | 97 % of `custom_components/thermia_cloud` |

## Gold (not a goal for v0.1, what exists)

Diagnostics with redaction, reconfigure flow, Repair issues, devices with child devices, curated
translated entity names. Missing: dynamic device discovery without reload, translated exception
messages for every client error, full entity-category/icon translations.
