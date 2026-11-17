# Notice and credits

**Thermia Cloud (unofficial) for Home Assistant** is a community project. It is not affiliated with, endorsed by, or supported by Thermia, Danfoss, or the Home Assistant project / Nabu Casa. "Thermia" is used only to describe compatibility.

## Prior work

This project was inspired by, and learned a great deal from, two GPL-3.0 projects by **klejejs**:

- [`python-thermia-online-api`](https://github.com/klejejs/python-thermia-online-api) — the Python client for the Thermia Online cloud.
- [`ha-thermia-heat-pump-integration`](https://github.com/klejejs/ha-thermia-heat-pump-integration) — the original Home Assistant integration.

Their work made the research for this project possible; thank you. The sign-in client and everything else in this repository is an **independent implementation** written from a protocol description (`docs/API-NOTES.md`) and contains no code copied from those projects.

Everything we wrote is distributed under **GPL-3.0-or-later** (see `LICENSE`).

## Third-party texts

Label texts (register, group and value names) are downloaded from Thermia's cloud service (its localization endpoint) and redistributed as short UI labels in `custom_components/thermia_cloud/catalog/i18n/`. They remain the property of their owner. If you are the rights holder and object, please open an issue and they will be removed.
