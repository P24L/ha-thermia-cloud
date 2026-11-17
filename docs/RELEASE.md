# Release and publishing

## 1. What is where

| Channel | What it is | Who can use it | Effort |
|---|---|---|---|
| **GitHub repo + Release** | the source of truth | everyone | low |
| **Marketplace "Add from link"** | Home Assistant 2026.11 has the former HACS built in as *Settings → Marketplace*; any public GitHub repo can be added by URL | users on 2026.11+ (legacy HACS for ≤ 2026.10) | none beyond a good repo |
| **Marketplace/HACS default catalog** | searchable by everyone without adding a link | everyone | PR to `hacs/default`, review can take **months** |
| **HA core** | ships with HA | everyone | very high (PyPI lib, 100 % coverage, quality scale, maintainers' acceptance; reverse-engineered cloud APIs are a hard sell) — stretch goal |

Marketplace facts (official page <https://www.home-assistant.io/integrations/marketplace/>, read 2026-11-17):

- *Add from link* needs a **public GitHub repo with a `hacs.json`** (a custom repo without it stays installed but **cannot be updated**), one content type, correct folder structure; apps are rejected. The user needs the GitHub device sign-in connection for custom repos.
- Installing a new integration goes straight into its setup flow, **usually without a restart** (the Marketplace page says some integrations still need one); after an *update* a restart is needed (a Repair reminds and can restart).
- The catalog is checked every 6 h; **custom repos with a GitHub connection every 48 h**. Each installed project gets an `update` entity.
- **Only stable releases are offered by default**; users can enable a *Pre-release* switch (off by default) and *Install another version*. → publish normal `0.x` releases; keep the pre-release flag for release candidates.
- If the latest release needs a newer HA than the user's, the dialog offers older versions (the minimum-version key is not named on that page — we use `homeassistant` in `hacs.json`).
- A domain equal to a core integration triggers a warning and overrides core (not our case).
- Catalog listing: the page does not describe how to get listed; a custom repo that later enters the catalog is simply treated as a catalog repo. Follow the HACS rules in §5. Catalog removals happen when a project is unmaintained.
- Users are told community content is not audited/supported by the HA project; issues go to **our** tracker.

## 2. Repository requirements (HACS)

- Public, on GitHub; **description**, **topics**, **issues enabled**, README with usage.
- One integration per repo, under `custom_components/thermia_cloud/` (only that folder is installed).
- `custom_components/thermia_cloud/manifest.json` with `domain`, `name`, `version`, `documentation`, `issue_tracker`, `codeowners` (+ `config_flow`, `iot_class`, `integration_type`).
- `hacs.json` (**mandatory** for custom repositories) with at least `name`; we add `homeassistant` (minimum version) and `render_readme`.
- **Brand images** in `custom_components/thermia_cloud/brand/` (`icon.png` 256×256, `icon@2x.png` 512×512; optional `logo*.png`, `dark_*`) — supported since HA 2026.3. Our own generic drawing, **not** the Thermia logo.
- OSI-approved license identifiable by GitHub (GPL-3.0 ✔).
- **GitHub Releases** (not only tags); manifest `version` = release tag without `v`.

Suggested GitHub topics: `home-assistant`, `hacs`, `homeassistant-integration`, `thermia`, `heat-pump`, `custom-component`, `iot`.

CI (`.github/workflows/`): `validate.yml` (hassfest + `hacs/action` with `category: integration`), `tests.yml` (ruff, mypy, pytest on Python 3.14), `release.yml` (on tag: verify manifest version, build release notes from `CHANGELOG.md`, create the GitHub release).

## 3. Versioning

SemVer. `0.x` = beta (breaking changes allowed, noted in release notes). Because the Marketplace offers only stable releases by default, publish regular GitHub releases from `v0.1.0` and say "beta" in the notes; use the *pre-release* flag only for release candidates.

## 4. Release checklist (copy for each release)

- [ ] `CHANGELOG.md` updated (Added/Changed/Fixed, breaking changes first)
- [ ] `manifest.json` version bumped; `hacs.json` min HA still right
- [ ] CI green: hassfest, HACS action, ruff, mypy, pytest
- [ ] Localization snapshot refreshed if needed (`scripts/sync_localization.py`), diff reviewed
- [ ] `scripts/live_smoke.py` passes against a real account (read-only)
- [ ] Tested on the dev HA (Mac) and, for minor/major, on the maintainer's HA (read-only first)
- [ ] README/docs screenshots current
- [ ] `git tag vX.Y.Z && git push --tags` → release workflow creates the GitHub release
- [ ] Verify on the maintainer's HA: Marketplace shows the new version → update → restart → entities OK
- [ ] Announce (release notes; HA community post for major milestones)

## 5. Getting into the default catalog (after a few stable releases)

Per `hacs.xyz/docs/publish/include` (fetched 2026-11-17):

- [ ] Repo works as a custom repository, is public, active (not archived)
- [ ] HACS Action passes **without errors or ignores**; hassfest passes
- [ ] A full GitHub release exists
- [ ] Domain does not collide with a core integration (checked: `thermia_cloud` is free)
- [ ] Brand icon present; `hacs.json` has `name`; JSON lints; description + topics + issues present
- [ ] Submit **from your personal fork** (not an organization), branch from `master`, add the repo **alphabetically** to the `integration` file of `hacs/default`; fill in the PR template honestly
- [ ] Be patient: reviews can take months; minor issues → draft PR, major issues → closure
- [ ] After merge the repo appears with the next scheduled scan

## 6. Support and issue handling

- Issue templates: *Bug* (requires diagnostics download + HA version + integration version + Thermia model/profile), *New model / unknown registers* (asks for diagnostics → anonymizer → fixture PR), *Feature*.
- `SECURITY.md`: credentials are the sensitive asset; report privately.
- Policy: we do not promise support for models we have no fixture for; contributions of fixtures are the path.

## 7. Path to HA core (optional, later)

1. Extract `client/` to PyPI as `thermia-cloud` (own repo, tests, typed, async-only).
2. Integration uses the PyPI package; 100 % test coverage of config flow, quality-scale bronze+ (preferably silver).
3. Check the stance of core maintainers on reverse-engineered cloud APIs and Thermia's ToS first (open question, P10.3). If rejected, we stay a Marketplace integration — fully legitimate.
