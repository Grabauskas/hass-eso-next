# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-06-18

Initial release of `hass-eso-next`, a fork of
[`algirdasc/hass-eso`](https://github.com/algirdasc/hass-eso).

This is a HACS custom integration and intentionally does not register an
official brand in `home-assistant/brands`. The HACS validation workflow uses
`ignore: brands` for this reason, and the integration uses Home Assistant's
default icon.

### Changed
- Renamed the Home Assistant domain from `eso` to `eso_next` (directory,
  `DOMAIN`, services `eso_next.*`, and the `eso_next_tfa_required` event).
- Raised the minimum Home Assistant version to **2025.11.0**, matching the
  recorder external-statistics API the integration uses (`mean_type` /
  `unit_class`). Verified against the 2025.11 recorder API; no code migration
  was required.
- Updated `manifest.json`: code owner `@Grabauskas`, new documentation and
  issue-tracker URLs, version `0.1.0`, a declared `recorder` dependency, an
  `iot_class` of `cloud_polling`, and hassfest-conformant key ordering.
- Upgraded `hacs.json` to the current form with an accurate minimum HA version.

### Added
- GitHub Actions: pytest + coverage, `hassfest` + HACS validation, `ruff` lint,
  and tag-driven release automation.
- Characterization tests for dataset parsing and the `fetch` guard paths.
- Rebuilt documentation: a from-scratch `README.md`, an updated Gmail setup
  guide, and a new login-flow architecture document.

### Removed
- The upstream donation / "Buy Me A Coffee" section (not applicable to this
  fork).
- Unused imports: `EVENT_HOMEASSISTANT_STARTED` and `Event` from `__init__.py`, and
  an unused `ZoneInfo` import from `eso_client.py`.
- Raw developer artifacts (`docs/email.txt`, the saved TFA HTML page) and the
  upstream `manual-flow.md` (replaced by `docs/login-flow.md`).

### Fixed
- Cost statistics are no longer inserted as all-zero values when no price
  statistics exist for the period. `async_insert_cost_statistics` now skips
  insertion on empty price data; the guard previously tested `prices is None`,
  but the price lookup returns an empty dict (never `None`) on the no-data
  path, so zero-cost rows were written instead. (Pre-existing upstream bug.)
