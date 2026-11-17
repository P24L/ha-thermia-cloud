# Catalog and localization

The catalog is the **only** place where we hard-code knowledge about registers. It is data, not code: YAML, validated by a schema, loaded in the executor, extendable by contributors with a pull request (no Python needed).

Everything *not* in the catalog still works (generic rules in `ARCHITECTURE.md` §4) — the catalog just makes it nicer and safer.

## 1. Files

```
custom_components/thermia_cloud/catalog/
  catalog.yaml          curated register knowledge
  schema.py             voluptuous schema (+ tests)
  loader.py             async load + merge with user overrides
  i18n/
    en-US.json … cs-CZ.json …   bundled label snapshots (16 cultures)
    _meta.json                  fetched_at, source, key counts
```

## 2. `catalog.yaml` format

```yaml
version: 1

# Physical parts → child devices (name keys live in translations/*.json)
devices:
  main:      {}                         # the installation device itself
  circuit_1: {translation_key: device_circuit_1}
  circuit_2: {translation_key: device_circuit_2}
  pool:      {translation_key: device_pool}

# Which device each register group belongs to + default entity category
groups:
  REG_GROUP_HEATING_CURVE:        {device: main}
  REG_GROUP_HEATING_CURVE_CIRC1:  {device: circuit_1}
  REG_GROUP_HEATING_CURVE_CIRC2:  {device: circuit_2}
  REG_GROUP_POOL:                 {device: pool}
  REG_GROUP_OPERATIONAL_TIME:     {device: main, category: diagnostic}
  # groups not listed here (e.g. REG_GROUP_HOT_WATER) default to device: main

registers:
  # Key = register name, or GROUP/NAME when the same name exists in several groups
  REG_HEATING_HEAT_CURVE:
    kind: number                 # sensor | binary_sensor | number | select | switch | skip
    unit: "°C"
    device_class: temperature
    icon: mdi:chart-bell-curve
    default_enabled: true        # created enabled
    risk: heating                # none | heating | service  → see §3
    translation_key: heating_curve     # curated short name from our translations/*.json
    description_key: desc_heat_curve   # optional

  REG_HEATING_HEAT_CURVE_MIN:
    kind: number
    unit: "°C"
    device_class: temperature
    default_enabled: false
    risk: heating

  REG_HEATING_HEAT_STOP:
    kind: number
    unit: "°C"
    device_class: temperature
    default_enabled: false
    risk: heating

  REG_SER_HOT_WATER_TOPH_INTER:   # REG_SER_* names look service-level: planner default risk is `service`,
    kind: number                  # so this curated entry states the intent explicitly
    unit: d
    risk: none
    default_enabled: false

  REG_OPER_TIME_COMPRESSOR:
    kind: sensor
    unit: h
    device_class: duration
    state_class: total_increasing
    category: diagnostic
    default_enabled: true

  REG_OPER_DATA_SUPPLY_MA_SA:
    kind: sensor
    unit: "°C"
    device_class: temperature
    default_enabled: true

  REG_GROUP_HOT_WATER/REG_OPERATIONMODE:   # GROUP/NAME key: same name exists in two groups
    kind: select                 # hot-water comfort mode (Comfort/Economy/Away); visible values win
    translation_key: hot_water_mode
    default_enabled: true

  REG_GROUP_OPERATIONAL_OPERATION/REG_OPERATIONMODE:
    kind: select                 # OFF/AUTO/COMPRESSOR/AUXILIARY/HOT_WATER, no min/max in the cloud
    translation_key: operation_mode
    risk: heating                # OFF is exposed without extra confirmation (DECISIONS D6)
    default_enabled: true

  REG_ACTIVATE_CIRC1:            # label in the cloud is "Aktivovat" but the values are Curve / Constant
    kind: select
    translation_key: circuit_mode
    risk: heating
    default_enabled: false

  REG_OPER_DATA_DISTR_CIR1:      # lives in TEMPERATURES, belongs to circuit 1
    kind: sensor
    unit: "°C"
    device_class: temperature
    device: circuit_1            # per-register device override
    default_enabled: true

  REG_PID:
    kind: sensor
    unit: "%"              # TO VERIFY — Thermia label is "Heat demand"
    state_class: measurement
    default_enabled: false

  COMP_HAS_LINK:
    kind: skip
```

> Keys of the form `GROUP/NAME` use the real group name. Lookup order: `GROUP/NAME`, then `NAME`. A plain `NAME` key is **rejected by the schema test** when that name occurs in more than one group of any fixture (e.g. `REG_OPERATIONMODE`), so a catalog entry can never silently apply to the wrong register. (`REG_HEATING_HEAT_CURVE*` is intentionally shared by the main and circuit-1 groups.)

Initial content = everything in the iTec profile fixtures (26 registers) + the registers the upstream library knows (`REG_BRINE_*`, `REG_RETURN_LINE`, `REG_COOL_SENSOR_*`, `REG_ACTUAL_POOL_TEMP`, `REG_OPER_DATA_BUFFER_TANK`, …) so other families get names/units even before anyone shares a dump.

## 3. `risk` flag

| Value | Meaning | Effect |
|---|---|---|
| `none` | harmless (e.g. display preferences) | normal |
| `heating` | changes how the building is heated (curves, limits, stop temperature, circuit activation) | `default_enabled` is set per register (e.g. the main heating curve is on; min/max/stop are off); entity description carries a freeze warning; excluded from any "enable all" bulk action in the options UI |
| `service` | installer-level parameters | the planner exposes the register **read-only** (a sensor) unless a user override says otherwise. (`kind: skip` is a different thing: no entity at all.) Unlisted `REG_SER_*` registers default to this class |

## 4. Overrides by the user (optional — editor not in v0.1, P10.8)

Stored in `config_entry.options["overrides"]`, applied **after** the catalog:

```json
{
  "overrides": {
    "REG_GROUP_HEATING_CURVE/REG_HEATING_HEAT_STOP": {
      "name": "Heating stop (outdoor)",
      "unit": "°C",
      "device_class": "temperature",
      "kind": "number",
      "enabled": true
    }
  }
}
```

Keys without a catalog entry appear in the **Unmapped registers** step (see `UI-DESIGN.md`). Overrides never change the cloud limits (min/max/step) — they cannot make a register more dangerous than the cloud allows.

## 5. Localization

### 5.1 Snapshots in the repo

`scripts/sync_localization.py`:

1. Logs in with env vars `THERMIA_USERNAME` / `THERMIA_PASSWORD` (never committed).
2. `GET /api/v1/languages` → cultures; `GET /api/v1/localization/{culture}` for each.
3. Keeps keys with prefixes `REG_`, `COMP_`, `REG_GROUP_` and every `valueNames[].name` seen in fixtures (alarm texts and UI texts are **not** copied).
4. Writes sorted `i18n/<culture>.json` + `_meta.json` (`fetched_at`, counts, tool version).

A CI job cannot run it (needs a real account) — maintainers run it before releases (roadmap P3.6) and review the diff.

### 5.2 Language and resolution

Option *Label language* (default **Auto = Home Assistant language**, English fallback; or any bundled culture explicitly — decision D16). `LabelResolver.label(key)` tries, in order:

1. **our own curated name** from `translations/<lang>.json` for registers/devices with a `translation_key`;
2. the refreshed copy in `.storage` (culture chosen above);
3. the bundled snapshot of that culture;
4. the same language in another culture (`cs` → `cs-CZ`);
5. `en-US`;
6. a humanized key (`REG_OPER_TIME_IMM1` → "Oper time imm1").

Edge cases seen in the live data (cs-CZ):
- English-only label for a Czech user (`REG_GROUP_HEATING_CURVE_CIRC1`) → next level; device names always come from our own translations.
- Label with an embedded unit ("Křivka [°C]"): the bracket is stripped from the display name **only if it is a known unit**; units are parsed from the **en-US** label through a fixed table, never from localized text ("Dní").
- Literal value names ("Comfort") are shown as is.
- Several registers share one cloud label ("Teplá voda" ×4): curated names plus the planner's collision pass (`ARCHITECTURE.md` §4.3).

### 5.2a Corrections of Thermia's texts (`i18n/overrides/`)

The bundled snapshots are verbatim copies of the cloud's texts and are never edited. Thermia's
texts have gaps (a quarter of each culture is still English) and a few mistakes, so corrections
live in `i18n/overrides/<culture>.json` (`{KEY: text}`) and win over the snapshot **and** over a
refreshed copy. They were produced machine-assisted (one pass per language, with the Czech ones
reviewed by the maintainer); native-speaker fixes are welcome as pull requests.
`scripts/clean_overrides.py` normalizes them (drops unknown keys, restores the English unit
bracket); `tests/catalog/test_translations.py` guards the format. The curated UI/entity names in
`translations/<language>.json` exist for all 15 languages Thermia offers.

### 5.3 Refresh on demand

- Button **Refresh names** (device page, diagnostic category). **No automatic/weekly refresh.**
- It fetches `/api/v1/localization/{culture}` (authenticated), filters exactly like the script, stores the result in `.storage/thermia_cloud.labels.<entry_id>`, then **reloads the entry**. User-renamed entities keep their custom name.
- Failure never blocks anything — the bundled snapshot is the baseline.

### 5.4 Legal note

Thermia's label texts are third-party content. See `DECISIONS.md` D4 for the accepted risk/mitigation.

## 6. Contributing catalog entries

1. Download diagnostics from the integration (redacted).
2. Run `scripts/anonymize.py diagnostics.json tests/fixtures/<family>_profile_<id>/`.
3. Add catalog entries + fixture + expected planner snapshot; CI validates the schema and snapshots.
