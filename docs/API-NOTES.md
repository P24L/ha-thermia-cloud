# Thermia cloud API — field notes

Reverse-engineered notes about the Thermia Online ("classic") cloud API used by the Thermia web app and by both upstream projects. Unofficial, undocumented, may change without notice.

Confidence: ✅ verified against the live cloud on 2026-11-17 (iTec heat pump, installation profile 1005) · ⚠️ inferred from code/bundles · ❓ unknown.

Sources: the public web app bundles (fetched with `python-thermia-online-api/scripts/fetch_thermia_web_app.py`), the upstream library, and authenticated read-only calls. Real fixtures: `tests/fixtures/itec_profile_1005/` (anonymized).

## 1. Discovery

`GET https://online.thermia.se/api/configuration` (public, no auth) ✅

Notable keys: `apiBaseUrl` (`https://online-classic-serviceapi.azurewebsites.net`), `authApiBaseUrl`, `authConfig` (`clientId`, `scopes` incl. `offline_access` and `openid`, `authorities.signIn` → `https://login.thermia.com/<tenant>/B2C_1A_SignUpOrSigninOnline/`, `nativeOverrides` for the mobile app), `isWebSocketEnabled` (**false**), `demoAccountNames`, `offlinePeriodMinimumsInMinutes`.

> The upstream library hard-codes the older host `thermialogin.b2clogin.com`; the public config now advertises `login.thermia.com`. We read the authority from this endpoint.

## 2. Authentication ✅/⚠️

Azure AD B2C, authorization-code flow with PKCE (S256), scraped HTML — no official API login:

1. `GET {authority}/oauth2/v2.0/authorize` (client_id = scope = `clientId`, redirect `https://online.thermia.se/login`, `code_challenge`) → HTML containing `var SETTINGS = {…}` (`transId`, `csrf`) + cookies.
2. `POST {authority}/SelfAsserted?tx=StateProperties=<transId>&p=B2C_1A_SignUpOrSigninOnline` with `signInName`, `password`, header `X-Csrf-Token`. `status != 200` or `{"status":"400"` in body = bad credentials.
3. `GET {authority}/api/CombinedSigninAndSignup/confirmed?csrf_token=…&tx=…&p=…` — final redirect URL contains `code=`.
4. `POST {authority}/oauth2/v2.0/token` (`grant_type=authorization_code`, `code_verifier`) → `access_token`, `expires_on`, optionally `refresh_token`.

Observed behaviour:
- ✅ Access tokens are rejected with `401` after roughly **1–2.5 h**, although the library assumes 6 h (observed 2026-11-15 in a maintainer-written client). → Always handle `401` centrally: re-auth once, retry once.
- ✅ (P0.1, 2026-11-17) The token response **does** contain a `refresh_token` (scopes `<clientId> offline_access openid`). Response keys: `access_token`, `expires_in` (3600), `expires_on`, `not_before`, `id_token`, `id_token_expires_in`, `profile_info`, `refresh_token`, `refresh_token_expires_in` (**86400**, i.e. 24 h), `resource`, `scope`, `token_type`. The `refresh_token` grant at the same `/oauth2/v2.0/token` endpoint (`client_id`, `scope`, `refresh_token`) returns 200 with a new access token that the API accepts; the **refresh token is rotated on every use** → always persist the newest one. ✅ **Sliding**: a probe refreshed the token every ~50 min for 24.7 h (27 rotations, no failure), so the chain does not expire while it is used at least once a day (P0.3 probe, 2026-11-17/18). The access JWT lifetime (`exp`−`iat`) is 3600 s; measured (P0.2): the token was still accepted at 3608 s and refused at 3908 s, i.e. about **1 h** (the earlier 1–2.5 h observation was optimistic). The integration renews 120 s before `expires_on`.
- ⚠️ Terms-of-service/privacy-policy updates can break the login until the user accepts them in the web app (upstream README). Detection heuristics: Spike P0.6.
- ✅ B2C cookie quirk (found 2026-11-17): the `SelfAsserted` response *expires* `x-ms-cpim-trans` (and `x-ms-cpim-cache|…`), yet the following `confirmed` call still needs them, otherwise it answers `400 Bad Request`. A standard cookie jar that honours the expiry breaks the flow → `auth.py` tracks cookies by hand and ignores expiring ones. The `tx=StateProperties=<id>` query value must be sent verbatim (no percent-encoding of `=`).
- All API calls: `Authorization: Bearer <access_token>`.

## 3. Endpoints (base = `apiBaseUrl`)

| Purpose | Request | Notes |
|---|---|---|
| List installations | `GET /api/v1/installationsInfo` | ✅ `{totalCount, items[]}`; item: `id`, `name`, `model`, `deviceId`, `macAddress`, `isOnline`, `lastOnline`, `firmwareVersion`, `profile`, `status`, `location`, … |
| Count | `GET /api/v1/installationsInfo/count` | ✅ |
| Installation info | `GET /api/v1/installations/{id}` | ✅ contains `installationProfileId` |
| Status | `GET /api/v1/installationstatus/{id}/status` | ✅ `heatingEffect`, `heatingEffectRegisters`, `hotWaterTemperature`, `isOnline`, … The web app polls this **every 5 s**. |
| Groups of a profile | `GET /api/v1/installationprofiles/{profileId}/groups` | ✅ `[{id,name,parentId,visibility,description}]` — 23 groups for profile 1005 |
| Registers of a group | `GET /api/v1/Registers/Installations/{id}/Groups/{groupName}` | ✅ values + specification (see §4). Unavailable groups return `200 []`. |
| Write register | `POST /api/v1/Registers/Installations/{id}/Registers` body `{registerSpecificationId, registerValue, clientUuid}` | ✅ HTTP 200; value is **queued** for the device (see `queueId` in push messages) → read back may lag. |
| Registers available for history | `GET /api/v1/DataHistory/installation/{id}` → `{installationId, registers[]}` | ✅ 14 registers, **carries visibility conditions** (§5). Ids here are `registerIndex`, not `registerId`. |
| Alarms | `GET /api/v1/installation/{id}/events?onlyActiveAlarms=false` | ⚠️ |
| Languages | `GET /api/v1/languages` | ✅ 16 cultures (`en-US`, `cs-CZ`, `de-DE`, `sv-SE`, `pl-PL`, …) |
| Texts | `GET /api/v1/localization/{culture}` | ✅ `{culture, resources:[{key,value}]}`; `cs-CZ`: 1477 keys, 560 are `REG_*`/`COMP_*` |
| App feature flags | `GET /api/v2/FeatureVisibility?installationId={id}` | ✅ only app features (`smartTariff`, `danishTariff`, …) — **not** register visibility |
| Push | `wss://{apiBaseUrl host}/ws` | ⚠️ JSON-RPC 2.0 client exists in the web app (`Login{jwt}`, `Subscribe{installationId, registerIds}`, notification `valuesChanged{registerId, displayValue, minDisplayValue, maxDisplayValue, queueId, prioValue, prioUuid}`). Gated by `isWebSocketEnabled` (false) and `/ws` currently answers **404**. |
| "New" API | `https://api-prod.thermia.com/api/prod/user` | ❓ Appears only in `authConfig`; gateway answers JSON 404 for every route we tried; not used by the web app. Needs mobile-app traffic capture to learn more. |

Response shapes (2026-11-17, key names only): `installationsInfo` items carry `id`, `name`, `model`, `deviceId`, `serialNumber`, `macAddress`, `profile{}`, `status{}`, `retailerId`, `isOnline`, `lastOnline`, `retailerAccess`, `deviceConnectionType`, `firmwareVersion`, `owner`, `location{}`. In `installationsInfo` the `model` string was **empty** for the iTec test installation (live smoke); `installations/{id}` carries it. `installations/{id}` adds `installationProfileId`, `timeZoneId`, `address{}`, `hotwater{status}`, `heating{status}`, `hasLinkUnit`. `authConfig.authorities.signIn` is a plain string. Register `timeStamp` has **no zone**; `timeZoneId` of the installation is the likely reference (❓ unverified).

## 4. Register specification (what the cloud tells us) ✅

Per register in a group response:

| Field | Meaning / observations |
|---|---|
| `registerId` | Write id (`registerSpecificationId`), e.g. `110140` |
| `registerIndex` | Stable specification index, e.g. `1020`; used by history endpoint |
| `registerName` | Symbolic key, e.g. `REG_HEATING_HEAT_CURVE`. **Not unique across groups** — `REG_OPERATIONMODE` exists in `REG_GROUP_HOT_WATER` (id 114185) and `REG_GROUP_OPERATIONAL_OPERATION` (id 110030); `REG_HEATING_HEAT_CURVE*` exist in the main and the `_CIRC1` group |
| `groupName`, `groupId`, `groupOrder`, `groupItemOrder` | placement |
| `registerValue` | number; `stringRegisterValue` mostly `null` |
| `minValue`, `maxValue`, `step` | limits (null for read-only) |
| `isReadOnly` | write permission |
| `presentation` | seen: `Integer`, `Slider`, `Enumeration`, `StatusFlagsTextInd`, `Hidden`; web app also knows `StatusFlags`, `MultipleStatusFlags`, `PosixTime`, `SliderFormattedTime` |
| `valueNames[]` | `{name, value, visible, isReadonly, confirmation}`; `visible:false` entries are hidden in the web app |
| `modifier` | observed: `8` temperature, `12` temperature (supply), `1` heating-curve temperature, `16` hours, `0` none/other — **not reliable for units** (`REG_HEATING_HEAT_STOP` is °C with modifier 0; `REG_SER_HOT_WATER_TOPH_INTER` is days with modifier 0) |
| `unit` | **empty** (`NotSpecified` / `0`) on this profile |
| `timeStamp` | when the device last reported/changed the value (ISO, e.g. `REG_INDOOR_TEMPERATURE` 2024-06-02, `REG_OPER_DATA_SUPPLY_MA_SA` minutes ago) |
| `isInvisible`, `isComputedRegister`, `canBeShownInGraph`, `canBeShownInHistory`, `trueText`, `falseText`, `disabledByLink`, `collapsible`, `groupParentId` | present, mostly unused so far |

Profile 1005 (iTec) returns **26 registers**; **19 of 23 groups are empty**. The cloud silently drops what it does not want to show (e.g. `REG_PID`, "Heat demand", disappeared after the 2026-09-18 migration; most of it later recovered, `REG_PID` did not). Group `visibility` values `1/2/3/null` are not interpreted by the web app; their meaning is ❓. Profile 1005 (P0.10, single dump): every non-empty group has 1–3 (operation 1, heating curves 1, hot water 2, temperatures/status/time 3); every `null` group is empty and technical (diagnostics, software versions, calibration, calendar, errors, immersion heaters). 1–3 also appear on empty groups, so the value says nothing about whether data is returned → do not interpret it in v0.1.

`modifier` table seen on profile 1005 (P0.7, single dump): 8 = temperature, 12 = supply temperature, 1 = heating-curve temperature, 16 = hours, 0 = anything else (enums, status flags, `REG_HEATING_HEAT_STOP` °C, `REG_SER_HOT_WATER_TOPH_INTER` days). `0` carries no information. Open: difference between `StatusFlagsTextInd`, `StatusFlags` and `MultipleStatusFlags` (only the first occurs here).

## 5. Visibility conditions ✅

The history registers carry a tiny expression language deciding whether a register is shown:

```
{REG_DESIRED_SUPPLY_LINE_TEMP} >= 0
{REG_OPER_DATA_DISTR_CIR1} > 0
{REG_ACTIVATE_POOL} = 1
{REG_SER_AUX_HEAT_MAX_STEP} >= 1
{REG_OPER_TIME_HOT_WATER} > 0 AND {REG_OPER_TIME_HOT_WATER} < 65535
```

plus `disabledRegisterValue` (`-100` = sensor not connected). Fields: `registerVisibilityCondition`, `exclusiveVisibilityCondition`, `disabledRegisterValue`. References may point at registers that are **not** returned to us (`REG_SER_AUX_HEAT_MAX_STEP`) → policy: unresolved reference = "visible", reported in diagnostics. Grammar to confirm with more dumps (P0.5).

## 6. Status flags ✅/⚠️

`COMP_STATUS_ITEC` (presentation `StatusFlagsTextInd`) holds a bitmask; `valueNames` map bit values to `COMP_VALUE_COMPR`=1, `COMP_VALUE_RADIATORPUMP`=2 (`visible:false`), `COMP_VALUE_HOT_WATER`=8, `COMP_VALUE_HEATING`=16, `COMP_VALUE_DEFROST`=32, … Upstream decoding: `presentation == "StatusFlags"` → equality, otherwise `value & flag == flag`. Other families use other registers (`REG_OPERATIONAL_STATUS_PRIO1`, `COMP_STATUS_ATEC`, `COMP_STATUS`, `REG_OPERATIONAL_STATUS_PRIORITY_BITMASK`) — the generic rule covers all of them.

## 7. Texts ✅

Keys are per name, not per group (`REG_OPERATIONMODE` has one label). Examples (cs-CZ): `REG_HEATING_HEAT_CURVE` → "Křivka [°C]", `REG_HEATING_HEAT_CURVE_MIN` → "Přívod – minimum", `REG_HEATING_HEAT_STOP` → "Zastavení ohřevu", `REG_OPER_DATA_DISTR_CIR1` → "Směšovací okruh 1", `REG_PID` → "Heat demand". Gaps: some labels are English-only (`REG_GROUP_HEATING_CURVE_CIRC1`), some value names are literal ("Comfort"), units sometimes appear in brackets in the label.

## 8. Known quirks / traps

- Unavailable group → `200 []`, **not** an error. Missing register ≠ transport failure.
- Upstream library turns any non-200 into `[]` (so an expired token looks like "no data"). We raise typed errors.
- Writes return 200 even when the device is offline or the write is queued.
- Register timestamps differ widely; polling faster than the gateway uploads is pointless (measure: P0.3).
- Two different clients logging in with the same account coexist fine (a custom script and the HA integration run in parallel).

- ✅ **Registers can vanish at runtime** (2026-11-17): between 14:29 and 16:38 the cloud stopped returning hot-water `REG_OPERATIONMODE` (id 114185) and `REG_SER_HOT_WATER_TOPH_INTER` (the group answered with 1 instead of 3 registers); everything else, including other registers with 2024 timestamps, stayed. **Cause found later the same day: they exist only while hot water is ON** (`REG_HOT_WATER_STATUS` = 1). Hot water went off at 14:33 (its `timeStamp`) and both registers disappeared; when it was switched on again at 18:36 they came back (`REG_OPERATIONMODE` hot-water group = 0 *Comfort*, `REG_SER_HOT_WATER_TOPH_INTER` = 10). Like the circuit *Constant* register, availability depends on the state of another register. → the integration must treat a vanished register as `unavailable` + Repair, not as an error (roadmap P4.5/P6.5), and rediscovery must be able to bring it back.

- ⚠️ **Mode-dependent registers** (maintainer observation, 2026-11-17): in the official app a circuit set to *Constant* shows one parameter that the *Curve* mode does not, displayed as a raw technical register name (the cloud has no text for it). We have not seen which register this is — switching the mode is a write, so it has not been tried. The cloud's localization has constant-temperature texts (`REG_DC1_CONSTANT_TEMP_SET` "Desired constant temp", `REG_DISTRIBUTION_CIRCUIT_CONSTANT_DESIRED_TEMPERATURE`, …) but they probably belong to other families. Expected consequence: the cloud's register set for the circuit group changes with the mode (new register appears, curve registers may vanish). → `coordinator.py` notices registers it does not know (immediately) or planned ones missing for 3 polls and rediscovers (at most once per hour, persisted); new registers appear as generic disabled entities named after their key.

- ✅ **First live write** (2026-11-17, main-circuit heating curve 22 → 23 through the integration, the maintainer pressed it in a dev Home Assistant): `POST …/Registers` → **HTTP 200 with an empty body**; the register read back as the new value **3.1 s** after the POST (first fast-poll cycle); the register's `timeStamp` became the time of the write (about 0.3 s after the POST); a before/after comparison of all 24 registers showed no other setting changed (the circuit-1 curve stayed put). Read-only mode blocked two earlier attempts without any request reaching the cloud. Still unobserved: behaviour for an offline pump, the answer to a rejected value, long-running behaviour.

- ✅ **Circuit 1 in *Constant* mode** (2026-11-17, mode set to Constant by the maintainer): `REG_ACTIVATE_CIRC1` = 2 and the circuit-1 group answers with only two registers: `REG_ACTIVATE_CIRC1` and the new **`REG_HEATING_HEAT_CURVE1_CONSTANT`** (id 110159, index 1028, `Slider`, 20–55 step 1, modifier 1 = temperature, value 41, writable, no `valueNames`). The three curve registers (`REG_HEATING_HEAT_CURVE`, `_MIN`, `_MAX`) are **not returned** while the mode is Constant. The register has no text in the cloud's localization (any of the 16 cultures) — that is why the official app shows the raw key. It is not in the history list either. Fixture (rebuilt from the recorded response; the original file was overwritten by a later dump): `tests/fixtures/itec_profile_1005/mode_constant_group_REG_GROUP_HEATING_CURVE_CIRC1.json`. Integration behaviour: drift detection noticed the change within 3 polls and rediscovered (log: "The cloud's register set changed"); the curve entities stay in the entity registry as unavailable and come back when the mode returns to Curve.

- ✅ **Operation mode and hot water** (2026-11-17): `REG_OPERATIONMODE` value 4 (`HOT_WATER`) is returned with `visible: false` on this pump, so no "hot water only" mode is offered; the maintainer's newer app does it with the hot-water toggle. Observed with hot water ON and operation mode OFF: `COMP_STATUS_ITEC` = 0 (nothing running) at least in the first minutes.

- ✅ `GET …/installationstatus/{id}/status` carries `hasIndoorTempSensor` (false on the maintainer's pump). The indoor-temperature register is still returned (a stale 2024 value), so the integration reads the flag at setup and skips `REG_INDOOR_TEMPERATURE` when it is `false`; unknown/unreadable status hides nothing.

- ✅ **Status-flag visibility is state-dependent too** (2026-11-17): in `COMP_STATUS_ITEC` the *hot water* flag (value 8) is `visible: false` while hot water is off and visible while it is on (compressor 1, heating 16 and defrost 32 are always visible; radiator pump 2, pool 64 and cooling 128 hidden). A first installation made while hot water was off therefore saw it hidden → the integration keeps the four core flags enabled regardless of visibility.

- ✅ **Upload cadence** (P0.3, 24.7 h, polling every 2 min, 26 registers): a register's `timeStamp` changes only when the value is (re)reported, **not** on every poll. Measured gaps between device timestamps: supply line and circuit-1 temperature 1–2 min at the fastest, median ~10 min, max ~1.6 h; compressor/heating hours every ~1.8 h; hot-water temperature ~2.5 h; **outdoor temperature (moving average) median ~15 h, max 27.5 h** (it genuinely stands still for a day; the status endpoint's `outdoorTemperature` shows the same value); settings only when changed. Computed registers (`COMP_STATUS_ITEC`, `COMP_HAS_LINK`) get a fresh `timeStamp` at every read, so they say nothing about freshness. → 60 s polling is right for the fast values; slower polling would lose little, faster would gain nothing. A stuck value is not a stale-data signal by itself.
- ✅ **Time zones** (2026-11-18): register `timeStamp` values are the installation's **local time** (a supply-line value written 10 min earlier read `19:06` at 19:16 local), while `installationsInfo.lastOnline` is **UTC** and was within the last minutes: `lastOnline` is a usable liveness signal of the gateway (idea for P10.13).

- ✅ **Alarms** (2026-11-18): `installationsInfo[].status` carries `activeAlarms`, `activeCriticalAlarms`, `unreadErrors`, `unreadWarnings`, `unreadInfo` (counts). `GET /api/v1/installation/{id}/events?onlyActiveAlarms=false|true` returns `{totalCount, items[]}`; on the maintainer's pump `items` was empty in both cases, so the item shape (`eventTitle`, `isActiveAlarm` per the upstream project) is unverified.

## 9. Not yet explored

Alarms/events payloads, calendar/schedule registers, data-history download, smart-tariff features, the newer `api-prod.thermia.com` API, other profile families (Genesis, Atlas, Diplomat, ATEC) — fixtures from community diagnostics will tell.

## 10. Observations from the iTec fixture review (2026-11-17)

Verified against `tests/fixtures/itec_profile_1005/`:

- The history endpoint's `registerId` **is the `registerIndex`** of the live groups; `groupsInfo` entries are duplicated; condition references are by **name**, which is ambiguous for names that exist in two groups.
- `REG_OPER_DATA_POOL` and `REG_OPER_DATA_DISTR_CIR2` appear in the history list but in **no live group**; `REG_SER_AUX_HEAT_MAX_STEP` and `REG_ACTIVATE_POOL` are referenced by conditions but returned nowhere.
- **Hot-water `REG_OPERATIONMODE`** (`REG_GROUP_HOT_WATER`, id 114185): `maxValue = 1`, but the visible values are Comfort = 0, Economy = 1 (`REG_VALUE_MODE_ECONOMY`), Away = 2; hidden `REG_VALUE_STATUS_OFF`/`_ON` reuse the values 0/1. → validate against visible `valueNames`, *visible wins*.
- **Operational `REG_OPERATIONMODE`** (id 110030): `min/max = null`; values OFF(0), AUTO(1), COMPRESSOR(2), AUXILIARY(3), HOT_WATER(4); **every value carries `confirmation: UI_OPERATION_MODE_CHANGE_WARNING`** (the web app asks before changing it; we deliberately do not, DECISIONS D6).
- **`REG_ACTIVATE_CIRC1`**: 0 = OFF (hidden), 1 = CURVE, 2 = CONSTANT; the cloud label "Aktivovat" is misleading — it is a circuit mode.
- **`COMP_STATUS_ITEC` = 19** = 1 (compressor) + 2 (radiator pump, `visible:false`) + 16 (heating): hidden bits are set in normal operation. Hidden flags: radiator pump (2), pool (64), cooling (128).
- `REG_INDOOR_TEMPERATURE` has `timeStamp` 2024-06-02 and no visibility condition: a disconnected sensor presented as a normal register → stale rule (older than 30 days → created disabled).
- No hot-water **boost** register exists in this profile (the upstream integration probes `REG_HOT_WATER_BOOST`; it may exist on other families).
- `COMP_HAS_LINK` (index 10003, presentation `Hidden`) = 0 on an online pump; meaning unknown.
