# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-06-19

### Fixed
- **Cumulative statistics reset after import gaps.** `get_previous_sum` only
  looked back one hour and read the first row of that window, so any fetch gap
  longer than an hour (network outage, login/TFA failure) found no previous
  statistics, seeded the running `sum` from `0`, and corrupted the long-term
  energy/cost totals on the Energy dashboard from that point on. The lookback
  now spans 60 days and takes the most recent point before the import, with
  null-safe value extraction.

## [0.2.0] - 2026-06-19

Adds full UI configuration: the integration can now be installed, authenticated
(including the one-time-code step), and managed entirely from the Home Assistant
UI. Existing YAML configuration keeps working unchanged.

### Added
- **UI config flow** (`config_flow.py`; `config_flow: true` in the manifest).
  Set up an account from **Settings → Devices & Services → Add Integration**.
  The credential step validates the login against ESO. With IMAP details the
  one-time code is read automatically; without IMAP a native *Enter ESO code*
  step collects it. The same ESO username cannot be added twice
  (`already_configured`).
- **Object subentries.** Add, edit, and remove metering points from the config
  entry (name, object ID, consumed/returned toggles, optional price
  entity/currency). Duplicate object IDs are rejected within an entry and
  across other loaded accounts (`duplicate_object`).
- **Reconfigure flow.** Edit an existing entry's ESO password and IMAP settings
  without deleting it (entry menu → *Reconfigure*). Clearing the IMAP host
  switches the account to manual code entry; the price entity can likewise be
  cleared.
- **Reauth flow** for non-IMAP accounts. A scheduled login that needs a fresh
  code triggers Home Assistant's reauthentication prompt (`reauth_confirm` →
  `reauth_code`). The password is editable there, so a changed ESO password is
  fixed without re-adding the entry; the authenticated session then fetches
  immediately. `invalid_code` / `code_expired` keep the user from getting stuck.
- **Options flow** to change `notify_after_failures` on a UI entry at any time.
- **Per-entry device and entities.** A *Fetch now* button (`button.py`) and
  *Last fetch* (timestamp) + *Status* (enum) sensors (`sensor.py`), grouped
  under one device per account via `EsoBaseEntity` (`entity.py`). The sensors
  restore their last value across restarts and the status sensor exposes the
  last fetch error as an attribute.
- UI strings and entity name/state translations in English and Lithuanian
  (`strings.json`, `translations/en.json`, `translations/lt.json`).
- A setup-time warning when the same object ID is configured by more than one
  account (YAML and UI, or two UI entries), since both would write the same
  `eso:energy_*_{id}` statistics with independent running totals and corrupt the
  Energy dashboard history.
- Documentation: a "Configuration via the UI" section in the README and UI
  config-flow / reauth sequence diagrams in `docs/login-flow.md`.
- Unit tests for the new pure helpers (`config_model`, `const`) and additional
  `eso_client` login and `imap_client` coverage.

### Changed
- Extracted the per-account runtime into `EsoAccount` (`account.py`). Both the
  YAML path and the UI config-entry path build one and drive the same
  login/fetch/schedule/notify/statistics methods.
- Extracted shared constants into `const.py` and pure config helpers into
  `config_model.py` (`build_object`, `imap_provider_kwargs`, `imap_block`,
  `object_id_in_use`, `duplicate_object_ids`), keeping HA-free logic
  unit-testable.

There are no breaking changes: existing `eso:` YAML configuration continues to
work, and the minimum Home Assistant version is still **2025.11.0**.

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
