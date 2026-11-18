# Changelog

All notable changes are documented here. Format: [Keep a Changelog](https://keepachangelog.com/), versioning: [SemVer](https://semver.org/).

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
