# UI design (Home Assistant interface)

All screens use standard HA mechanisms (config flow, options flow, entity registry, repairs, diagnostics). Texts live in `translations/en.json` and `translations/cs.json`. ASCII mock-ups are sketches, not pixel specs.

## 1. Setup (config flow)

**Step 1 — Sign in**

```
┌ Thermia Cloud ─────────────────────────────┐
│ Sign in with your Thermia Online / MyThermia│
│ account.                                    │
│                                             │
│ E-mail     [____________________]           │
│ Password   [____________________]           │
│                                             │
│ ⓘ Unofficial integration, not affiliated   │
│   with Thermia or Danfoss.                  │
│                         [ Submit ]          │
└─────────────────────────────────────────────┘
```
Errors: `invalid_auth`, `cannot_connect`, `policy_acceptance_required` ("Log in once at online.thermia.se and accept the updated terms"), `unknown`.

**Step 2 — Installations** (shown only if the account has more than one)
Multi-select of installations (name, model, online). Default: all. Stored in the entry **options**, so it can be changed later.

**Step 3 — Finish**: entry title = account e-mail; one device per installation appears. No persistent notification is created; the finish dialog just offers to assign an area.

**Reconfigure**: change password/e-mail without losing entities (account identity = token `sub`, mismatch aborts). **Reauth**: started automatically only on a **definitive** wrong-credentials response — never on transient login failures; asks for the password only.

## 2. Devices and entities

```
Device: My Heat Pump                          (installation)
 ├ Sensors     Outdoor, Supply line, Desired supply line, Hot water (top),
 │             Compressor / Heating / Hot water / Aux heater hours (diagnostic) …
 ├ Binary      Compressor, Heating, Hot water, Defrost   (visible status flags only)
 ├ Controls    Heating curve [number] · Hot water switch · Hot water mode [select]
 │             Operation mode [select]
 │             Supply min / max, Heating stop [number, disabled by default — installer-level]
 └ Buttons     Refresh names · Rediscover registers  (diagnostic)

Device: Circuit 1 (child of My Heat Pump)
 ├ Sensors     Circuit 1 temperature
 └ Controls    Heating curve [number] · Supply min / max [number, disabled]
               Circuit 1 mode [select: Curve / Constant, disabled]
```

- Names are short (the device name is prepended by HA). **Curated** registers use our own translated names; the rest use Thermia's texts in the chosen language (`Křivka`, `Přívod – minimum`, `Zastavení ohřevu`). Duplicates on one device are disambiguated (`ARCHITECTURE.md` §4.3).
- Everything the catalog doesn't mark `default_enabled` is created **disabled** → user enables it in *Settings → Devices → Entities* like any other entity. No custom UI is needed for that.
- Writable controls expose `register_timestamp` and, on numbers, the cloud's min/max/step.
- Entities whose register vanished show `unavailable` with an explanatory attribute (and a Repair issue after 7 days).

## 3. Options flow (⚙ Configure)

Menu:

```
┌ Thermia Cloud — Configure ──────────────────┐
│ ▸ General                                   │
│ ▸ Installations & registers                 │
│ ▸ Names & language                          │
└─────────────────────────────────────────────┘
```

**General**
| Field | Default | Notes |
|---|---|---|
| Update interval (s) | 60 | 10–600 |
| **Read-only mode** | off | Opt-in monitoring-only mode; blocks all writes |
| Request timeout (s) | 30 | |
| Add raw register values as attributes | off | Debug aid |

**Installations & registers**
| Field | Default | Notes |
|---|---|---|
| Installations | all | Multi-select; changes add/remove devices |
| Show registers hidden by Thermia | off | Ignores *structural* visibility conditions |
| Expose unknown registers | on (disabled entities) | Generic entities for registers without catalog entry |

**Names & language**
| Field | Default |
|---|---|
| Label language | **Auto — follow Home Assistant language** (English fallback); or pick a culture |

Actions are **buttons on the device page**, not options-flow fields: *Refresh names* and *Rediscover registers* (diagnostic category). Changing the label language reloads the entry.

## 4. "Unmapped registers" editor — not in v0.1 (decided 2026-11-17)

> **Is it needed?** Names come from Thermia's translations, but *meaning* does not: unit, device class, `state_class` and kind. For the author's iTec profile only 2 of 26 registers lack a unit (both are in the catalog). The editor matters only for **unknown registers of other model families**, as a bridge until their entry lands in the catalog (via a diagnostics → fixture → catalog PR). Without it such a register still appears as a generic, disabled sensor/number — just without a unit.
> **How big is it?** Medium: an options-flow step with a register picker built from discovery, one form (kind, unit, device class, state class, name), validation that an override can never exceed the cloud's limits, storage in `options.overrides`, an entry reload, en/cs translations and tests for every branch — roughly 300–400 lines plus tests (about 1.5–2 days). The planner's merge step for overrides is small.
> **Decision:** not in v0.1; build it later only if users of other model families ask (roadmap P10.8).


For registers without catalog entry or without a resolvable unit:

```
┌ Unmapped register ──────────────────────────┐
│ REG_GROUP_HEATING_CURVE / REG_HEATING_HEAT_STOP
│ Cloud: writable · 0…40 · step 1 · modifier 0
│ Label:  "Zastavení ohřevu"                  │
│                                             │
│ Kind        [ Number ▾ ]                    │
│ Unit        [ °C ▾ ]                        │
│ Device class[ Temperature ▾ ]               │
│ Name        [ Zastavení ohřevu ]            │
│ ☐ Enable entity                             │
│ ⚠ Heating-related controls can freeze the   │
│   building if set wrongly.                  │
│                     [ Save ]  [ Skip ]      │
└─────────────────────────────────────────────┘
```
Saves to `options.overrides`, reloads the entry. Presented one register at a time with a register picker on the first screen (selector built from discovery).

## 5. Services

`thermia_cloud.set_register` (power users, for registers without an entity): target = a config entry/device, fields `group`, `register` (name or index), `value`. Registered in `async_setup`. It applies the **same policy as entities** (read-only mode, `risk: service` registers refused, validation against limits/visible enum values) and returns when the POST has been accepted — it does not wait for the read-back. (Documented exception to the "`entity_id` in services" rule, because the register may have no entity.)

## 6. Repairs

| Issue | Message (EN) | Fix |
|---|---|---|
| `policy_acceptance_required` | "Accept Thermia's updated terms" | not fixable in HA — link to online.thermia.se; clears itself when login works |
| `register_vanished_<name>` | "Thermia stopped providing *Heat demand*" | remove entity / ignore |
| `discovery_empty` | "Thermia returned no registers" | docs link + diagnostics |

(No `auth_failed` Repair: HA's own reauth flow is the surface for wrong credentials.)

## 7. Diagnostics download

Redacted JSON: integration/HA versions, installation meta (model, profile id; no name or ids), group list with counts, every register spec, the planner output (entity plans), visibility evaluation results incl. unresolved references, last errors, timestamps/latency, option set. This is the artifact users attach to issues and maintainers turn into fixtures.

## 8. Dashboards

No bundled custom card. README contains a copy-paste Mushroom/Entities example for the heating-curve controls.

## 9. Accessibility and i18n

All user-facing strings go through translations (`en`, `cs` from day one); error messages use `translation_key` so the UI language is respected; no emoji-only status.
