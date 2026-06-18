# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-06-18

Switched the integration to the `eso` domain so HACS and the Home Assistant
dashboard display the existing `eso` brand logo from `home-assistant/brands`
(HACS resolves the brand image by domain, with no repository-local override).

### Changed
- Renamed the integration domain from `eso_next` back to `eso` — component
  directory, `DOMAIN`, config key `eso:`, services `eso.*`, the
  `eso_tfa_required` event, the `eso_tfa` notification, and the `eso:energy_*`
  statistic IDs — to reuse the upstream `eso` brand logo on the HACS card and
  HA dashboard.
- Dropped `ignore: brands` from the HACS validation workflow, since the `eso`
  brand is registered upstream and now validates.
- Renamed the HACS display name to **ESO Energy Statistics Import with TFA**
  (`hacs.json` and the README title).

### Breaking
- Upgrading from 0.1.0 requires renaming the `eso_next:` key in
  `configuration.yaml` to `eso:` and updating any `eso_next.*` service calls or
  `eso_next_tfa_required` automations. Existing `eso_next:*` statistics are not
  migrated. The integration now shares the `eso` domain with `algirdasc/hass-eso`
  and cannot be installed alongside it.

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
- `statistics_builder` module holding the (Home Assistant-free) timestamp and
  cumulative-sum arithmetic, with unit tests covering the energy/cost row
  building and the cost-price key alignment. Added `tzdata` to the test
  requirements so `zoneinfo` resolves `Europe/Vilnius` on all platforms.
- Rebuilt documentation: a from-scratch `README.md`, an updated Gmail setup
  guide, and a new login-flow architecture document.

### Removed
- The upstream donation / "Buy Me A Coffee" section (not applicable to this
  fork).
- Unused imports: `EVENT_HOMEASSISTANT_STARTED` and `Event` from `__init__.py`.
- Raw developer artifacts (`docs/email.txt`, the saved TFA HTML page) and the
  upstream `manual-flow.md` (replaced by `docs/login-flow.md`).

### Fixed
- Cost statistics are no longer inserted as all-zero values when no price
  statistics exist for the period. `async_insert_cost_statistics` now skips
  insertion on empty price data; the guard previously tested `prices is None`,
  but the price lookup returns an empty dict (never `None`) on the no-data
  path, so zero-cost rows were written instead. (Pre-existing upstream bug.)
- Cost statistics no longer silently compute to zero on hosts whose system
  timezone is not `Europe/Vilnius`. `parse_dataset` now interprets ESO
  wall-clock timestamps in `Europe/Vilnius` and emits true UTC epochs, so the
  per-hour price lookup (keyed by the recorder's UTC hour boundaries) matches
  instead of missing. Energy timestamps are unaffected.
- Hard fetch failures (not logged in, wrong page, or a network error) now raise
  `ESOFetchError` instead of returning an empty result. Previously such a
  failure was indistinguishable from "ESO had no data" and reset the failure
  counter, so a persistent login/network breakage never triggered the
  retry/notification path. A failed fetch also no longer caches an empty
  dataset that would mask a later retry.
- `async_auto_import` now no-ops in manual mode (no `imap:` block) instead of
  attempting a login that always raises.
