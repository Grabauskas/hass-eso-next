# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Home Assistant custom integration (`eso`) that scrapes hourly energy
statistics from the Lithuanian ESO self-service portal (`mano.eso.lt`) and
writes them into Home Assistant's recorder as external long-term statistics for
the Energy dashboard. It is a maintained fork of `algirdasc/hass-eso`.

There is no published PyPI package — it ships as a HACS custom repository and as
a directory copied into `config/custom_components/`.

## Commands

```bash
pip install -r requirements-test.txt
python -m pytest                              # tests + coverage (config in pyproject.toml)
python -m pytest tests/test_form_parser.py    # single file
python -m pytest tests/test_eso_client_login.py::test_name   # single test
python -m ruff check .                         # lint
```

CI (GitHub Actions) runs three gates that must pass: `pytest` on Python
3.11/3.12/3.13, `ruff check .`, and Home Assistant `hassfest` + HACS validation.
hassfest requires `manifest.json` keys to stay sorted.

## Architecture

The integration is split into HA-runtime glue modules (excluded from unit tests
and coverage — see `pyproject.toml` `omit`; exercised only inside a running HA
instance) and pure-logic modules that are unit-testable without Home Assistant
installed.

The same per-account runtime (`EsoAccount`) backs both configuration paths: the
legacy YAML `eso:` block and UI-created config entries. Both build an
`EsoAccount` and call the same login/fetch/schedule/statistics methods.

**HA-runtime glue:**

- `custom_components/eso/__init__.py` — defines the voluptuous `CONFIG_SCHEMA`
  (YAML config under the `eso:` key), registers the `fetch_now` / `start_login`
  / `submit_tfa_code` services, sets up/unloads/reloads UI config entries, and
  warns when the same object ID is configured by more than one account. Builds
  `EsoAccount` instances for both the YAML and config-entry paths.
- `account.py` — `EsoAccount`: per-account runtime. Drives login, fetch,
  schedule, failure notification, and converts ESO datasets into `StatisticData`
  written through `async_add_external_statistics`. Tracks last-fetch
  time/status/error (surfaced by the sensors) and fires `SIGNAL_UPDATE`.
- `config_flow.py` — the UI config flow: account setup (`user`) with login
  validation, native TFA step (`tfa`), reauth (`reauth_confirm` →
  `reauth_code`), reconfigure (edit password/IMAP), an options flow
  (`notify_after_failures`), and the object subentry flow (add/edit/remove
  metering points). Delegates pure shaping to `config_model.py`.
- `entity.py` / `button.py` / `sensor.py` — per-entry device entities:
  `EsoBaseEntity` (shared device info), the *Fetch now* button, and the
  *Last fetch* + *Status* sensors.
**Pure logic (HA-free, unit-tested):**

- `const.py` — shared constants (config keys, `DOMAIN`, `SIGNAL_UPDATE`,
  `ENERGY_TYPE_MAP`, defaults). Imported by both glue and pure modules and by
  tests.
- `config_model.py` — pure helpers turning raw config/form dicts into runtime
  shapes: `build_object`, `imap_provider_kwargs`, `imap_block` (UI form →
  stored IMAP block, `None` when the host is blank), `object_id_in_use`, and
  `duplicate_object_ids` (cross-account statistic-ID collision detection).
- `eso_client.py` — `ESOClient`: the scraping/login state machine. Posts
  credentials, detects the TFA challenge form, submits the emailed code, then
  fetches the Drupal AJAX consumption endpoint and parses the JSON into
  `{consumption_type: {unix_ts: kwh}}`. The `unix_ts` keys are **true UTC
  epochs**: `parse_dataset` reads ESO's wall-clock strings as `Europe/Vilnius`
  so they are host-timezone independent and line up with recorder statistic
  keys. Holds session cookies and a `_pending` TFA challenge with a 15-minute
  TTL. Hard fetch failures raise `ESOFetchError` (distinct from "no data").
- `form_parser.py` — `FormParser` (stdlib `HTMLParser` subclass): extracts
  Drupal hidden form fields (`form_id`, `form_build_id`, `form_token`, `action`)
  from returned HTML. Distinguishing `form_id` values (`TFA_FORM_ID`,
  `CONSUMPTION_FORM_ID`) is how the client knows which page it landed on.
- `imap_client.py` — `ImapCodeProvider`: connects over IMAP/SSL and polls for
  the one-time login code email, matching by sender/subject and picking the
  newest message fresher than the login timestamp (with clock skew). Pure
  helpers (`extract_code`, `pick_code`, `build_search_criteria`) are tested
  directly.
- `statistics_builder.py` — pure (HA-free) helpers that turn ESO datasets into
  the `{start, state, sum}` rows written as statistics: `local_datetime` (UTC
  epoch → `Europe/Vilnius`-aware datetime), `build_energy_rows`, and
  `build_cost_rows`. Kept out of `__init__.py` so the timestamp / cumulative-sum
  arithmetic stays unit-testable.

### Login / TFA flow (two modes)

ESO emails a one-time code on every login. The same `ESOClient` drives both:

- **Auto mode** (`imap:` block configured): `client.login()` posts credentials,
  and if a TFA form appears, calls `code_provider.wait_for_code(...)` to read
  the code over IMAP, then submits it. Runs on the daily schedule; `fetch_now`
  triggers it on demand.
- **Manual mode** (no `imap:`): split across two services. `start_login` does
  only the credential POST (`client.start_login()`), fires the
  `eso_tfa_required` event and a notification; `submit_tfa_code` calls
  `client.submit_code(code)` then imports. Without IMAP, `login()` raises
  `TfaCodeNeeded`.

See `docs/login-flow.md` for the full sequence.

### Statistics model

- Statistic IDs are `eso:energy_{consumed|returned|cost}_{object_id}`.
- Consumed = ESO key `P+`, returned = `P-` (`ENERGY_TYPE_MAP`).
- Stats carry a running `sum` seeded from the recorder's previous hour
  (`get_previous_sum`), because HA long-term statistics are cumulative.
- All timestamps are localized to `Europe/Vilnius`.
- Cost stats are optional (`price_entity`): the price is read back from the
  price entity's hourly recorder statistics. When no price data exists, cost
  insertion is **skipped entirely** rather than writing zeros — preserve this.

## Conventions

- Target Python 3.11 (`pyproject.toml`); ruff line-length 100, `E501` ignored.
- Some log messages and inline comments are in Lithuanian — match the
  surrounding language when editing nearby code.
- Tests import the component modules via a synthetic top-level `eso`
  package set up in `tests/conftest.py`, which deliberately avoids executing
  `__init__.py` (its HA imports are unavailable). Keep new pure logic in the
  client/parser modules (not `__init__.py`) so it stays testable.
- HTML/email fixtures live in `tests/fixtures/`.
