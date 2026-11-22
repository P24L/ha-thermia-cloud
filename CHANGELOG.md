# Changelog

All notable changes are documented here. Format: [Keep a Changelog](https://keepachangelog.com/), versioning: [SemVer](https://semver.org/).

## [0.2.3] - 2026-11-22

### Fixed
- The *Names & language* options step no longer lists a directory inside Home Assistant's event loop (Home Assistant logged a blocking-call warning).

## [0.2.2] - 2026-11-18

### Changed
- Heating circuit devices are named after the heat pump ("My Heat Pump - Mixing circuit 1"), so they sit right behind it in the device list and are clear with several installations. Existing devices are renamed on update; entity ids do not change.

## [0.2.1] - 2026-11-18

### Added
- A **water heater** entity for the hot water (standard Home Assistant card and voice control): on/off and the comfort / economy / away modes, with the current hot water temperature. The switch, select and sensor stay.

## [0.2.0] - 2026-11-18

### Added
- **Setup wizard:** a final question asks whether the integration may *monitor and control* or only *monitor* (read-only). Options are grouped into collapsible sections with icons; *Read-only mode* sits under *Safety*.
- **Icons** for the main entities (temperatures, hot water, compressor, heating, defrost, modes, alarms), with state-dependent icons for switches and status flags.
- **Connection and alarms:** *Online* and *Last contact* (the gateway's last contact with the cloud, UTC) and *Alarm* / *Active alarms* from the installation status, re-read every 5 minutes. The alarm counts have not yet been seen with a real alarm on a live pump.
- **Hot water boost** switch; the other families' entries (return line, brine, tank, pool, circuit 2, status registers of ATEC/Diplomat/NCP); the model name now comes from the profile.
- **Getting started guide** (`docs/GETTING-STARTED.md`), two automation blueprints (alarm notification, connection lost) and screenshots.
- A tool to turn downloaded diagnostics into test fixtures, so users of other models can help (`scripts/diagnostics_to_fixture.py`).
- Registers that only exist in some state (circuit mode, hot water on/off) keep their entities, which turn unavailable and come back; unknown new registers trigger a rediscovery.
- If the first load of one of several installations fails, the others start and the failing one is retried in the background.

### Changed
- Heating stop temperature and the heating curve minimum/maximum are enabled by default (existing entities the integration had disabled are enabled on update).
- The four core status flags (compressor, heating, hot water, defrost) are enabled even while the cloud hides them; read-only or hidden enum values are never offered as choices; switches only for real off/on pairs; unitless room-factor and curve-offset registers no longer show degrees; hour counters ignore tiny dips.
- Translations for the new strings in all 15 languages.

### Fixed
- The B2C policy name is read from the advertised authority; a write error now includes the cloud's answer.

## [0.1.0] - 2026-11-18

First public beta. Verified against a real iTec heat pump (profile 1005): reading in production
(read-only mode), reading and writing in a development Home Assistant.

### Added
- Setup through the UI with your Thermia Online / MyThermia account; several installations per account; reauth and reconfigure flows.
- Entities discovered from the cloud's own description of the heat pump: sensors, binary sensors (visible status flags), numbers, selects and switches, with the cloud's limits and enumeration values; child devices for mixing circuits and pool.
- Control: hot water on/off, operation mode, heating curve (main and circuit 1) and the other writable registers (installer-level ones are created disabled). Optional **read-only mode**; values are validated, shown immediately and read back; action `thermia_cloud.set_register`.
- Registers that exist only in some state (circuit *Curve*/*Constant*, hot water mode and boost interval while hot water is on) keep their entities, which turn unavailable instead of being lost; unknown new registers trigger an automatic rediscovery.
- Entity names in 15 languages (our own short names where we have them, Thermia's texts otherwise) with a *Refresh names* button; corrections of Thermia's texts are kept separately.
- Options (update interval, read-only mode, timeout, installations, show hidden/unknown registers, label language), Repair issues, downloadable diagnostics with redaction.
- Catalog entries for the iTec profile and first entries for other families (ATEC, Diplomat, NCP/Atlas) taken from older-cloud dumps.

### Known limitations
- Only the iTec family has been checked against a live account; other families are expected to show their registers but are unverified.
- Writing has not been verified on a production installation yet, and the behaviour for an offline heat pump is unobserved (the cloud queues writes).
- If the first load of one of several installations fails, the others wait (P10.16).
