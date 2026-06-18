# How the ESO login / one-time-code flow works

ESO's portal (`mano.eso.lt`) requires a username/password login and then emails
a 6-digit one-time code (TFA) on every login. This integration automates that
flow. This document describes the moving parts so you can reason about failures.

## The flow

1. **Credential POST.** `ESOClient._start_credentials()` posts the username and
   password to `https://mano.eso.lt/?destination=/consumption`. ESO responds
   with either the consumption page (no TFA needed) or a TFA form
   (`gpc_tfa_login_auth_form`).
2. **Detect the challenge.** `FormParser` scans the response HTML for the form's
   `action`, `form_build_id`, and `form_id`. If the `form_id` is the TFA form,
   a pending login is stored (action URL + build id + timestamp).
3. **Obtain the code.**
   - *Auto mode:* `ImapCodeProvider.wait_for_code()` polls the configured
     mailbox over IMAP, searching for the newest message from `savitarna@eso.lt`
     with the expected subject, and extracts the 6-digit code with a regex.
   - *Manual mode:* the integration fires `eso_tfa_required` and raises a
     notification; you submit the code via `eso.submit_tfa_code`.
4. **Submit the code.** `ESOClient._submit_tfa()` posts the code to the TFA
   action URL. On success the session lands on the consumption page.
5. **Fetch data.** `ESOClient.fetch_dataset()` posts to the Drupal AJAX endpoint
   and parses the returned datasets into `{timestamp: kWh}` maps, which
   `__init__.py` turns into Home Assistant long-term statistics.

## Timing & safety rails

- A pending TFA code is only valid for 15 minutes (`TFA_CODE_TTL`); submitting
  after that raises `TfaCodeNeeded` and you must start again.
- The IMAP poller only accepts emails newer than the moment login started
  (minus a small clock-skew allowance), so a stale code from a previous attempt
  is never reused.
- In auto mode, repeated failures raise a persistent notification after
  `notify_after_failures` consecutive failures and retry later.

## Module map

| Module           | Responsibility                                            |
|------------------|-----------------------------------------------------------|
| `eso_client.py`  | Login, TFA submission, data fetch + dataset parsing       |
| `form_parser.py` | Extract Drupal form fields from response HTML             |
| `imap_client.py` | Find and extract the one-time code from the mailbox       |
| `__init__.py`    | HA wiring: config schema, services, schedule, statistics  |
