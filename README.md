# ESO Energy Statistics Import with TFA (`hass-eso-next`)

> **Fork notice.** This is a maintained fork of
> [`algirdasc/hass-eso`](https://github.com/algirdasc/hass-eso). It preserves the
> original integration's behavior and adds rebuilt documentation, tests, CI, and
> SemVer versioning. Thanks to the upstream author for the original work.

A Home Assistant custom integration that imports energy statistics from the
[ESO](https://mano.eso.lt/) self-service portal into the Home Assistant Energy
dashboard. It is for users with smart ESO meters who cannot add a P1 interface.

ESO publishes data for the last 24 hours, so the refresh rate is slow (a check
runs roughly every couple of hours). For real-time figures, use a P1 interface
or a third-party meter (e.g. Shelly 3EM).

## Requirements

- Home Assistant **2025.11.0** or newer (the integration uses the current
  recorder external-statistics API: `mean_type` / `unit_class`).

## Installation

> [!IMPORTANT]
> This integration uses the same `eso` domain as the upstream
> [`algirdasc/hass-eso`](https://github.com/algirdasc/hass-eso). The two cannot
> coexist — **uninstall `algirdasc/hass-eso` (and remove it from HACS) before
> installing this one**, then restart Home Assistant.

### HACS (custom repository)

1. HACS → Integrations → **Custom repositories**.
2. Repository URL: `https://github.com/Grabauskas/hass-eso-next`.
3. Category: **Integration** → **Add**.
4. Install, then configure (below) and restart Home Assistant.

### Manual

1. Copy `custom_components/eso` into your HA `config/custom_components/`.
2. Configure (below) and restart Home Assistant.

## Configuration

Add an `eso:` block to `configuration.yaml`.

### Integration

| Name                    |  Type   | Required | Default | Description                                         |
|-------------------------|:-------:|:--------:|:-------:|-----------------------------------------------------|
| `username`              | string  |   yes    |         | ESO username / email                                |
| `password`              | string  |   yes    |         | ESO password                                        |
| `imap`                  |  map    |    no    |         | Mailbox to read the login code from (auto mode)     |
| `notify_after_failures` | integer |    no    |    2    | Notify after this many consecutive auto-login fails |
| `objects`               |  list   |   yes    |         | List of objects                                     |

### IMAP (auto mode)

ESO emails a one-time code on every login. Provide an `imap:` block to let the
integration read that code automatically.

| Name       |  Type   | Required | Default                            | Description                       |
|------------|:-------:|:--------:|:----------------------------------:|-----------------------------------|
| `host`     | string  |   yes    |                                    | IMAP server (e.g. imap.gmail.com) |
| `port`     | integer |    no    | 993                                | IMAP SSL port                     |
| `username` | string  |   yes    |                                    | Mailbox login                     |
| `password` | string  |   yes    |                                    | Mailbox app password              |
| `folder`   | string  |    no    | INBOX                              | Folder to search                  |
| `sender`   | string  |    no    | `savitarna@eso.lt`                 | Match emails from this sender     |
| `subject`  | string  |    no    | `ESO - Prisijungimo patvirtinimas` | Match this subject                |

For a step-by-step dedicated-Gmail walkthrough, see
[docs/gmail-setup.md](docs/gmail-setup.md). For how the login/TFA flow works,
see [docs/login-flow.md](docs/login-flow.md).

> **Security tip.** Do not point this at your main inbox. Use a dedicated
> mailbox that only ever receives forwarded ESO codes, protected by an app
> password.

### Object

| Name             |  Type   | Required | Default | Description                                          |
|------------------|:-------:|:--------:|:-------:|------------------------------------------------------|
| `name`           | string  |   yes    |         | Name of object (visible in the energy dashboard)     |
| `id`             | string  |   yes    |         | Object ID (see *How to get your object ID*)          |
| `consumed`       | boolean |    no    |  True   | Generate statistics for consumed energy              |
| `returned`       | boolean |    no    |  False  | Generate statistics for returned energy              |
| `price_entity`   | string  |    no    |         | Entity tracking electricity price                    |
| `price_currency` | string  |    no    |   EUR   | Currency of electricity price                        |

### Example

```yaml
eso:
  username: your_username
  password: your_password
  objects:
    - name: My House
      id: 123456
      returned: True
    - name: My Flat
      id: 654321
```

### How to get your object ID

1. Log in to your ESO account.
2. Open your [objects page](https://mano.eso.lt/objects).
3. Click the object you want.
4. The number in the address bar (`https://mano.eso.lt/objects/123456789`) is
   your object ID.

### Example with cost calculation

Using the [Nord Pool integration](https://github.com/custom-components/nordpool)
to provide an hourly price entity:

```yaml
sensor:
  - platform: nordpool
    region: "LT"
    currency: "EUR"
    VAT: true
    precision: 5
    low_price_cutoff: 0.95
    price_in_cents: false
    price_type: kWh
    additional_costs: "{{ 0.08470 + 0.007 | float }}"

eso:
  username: your_username
  password: your_password
  objects:
    - name: My House
      id: 123456
      price_entity: sensor.nordpool_kwh_eur_ext
```

Point `price_entity` at the price entity to create an extra entity tracking
energy cost. In the Energy dashboard, choose *Use an entity tracking the total
costs* and select `My House (cost)`.

## Auto mode vs manual mode

### Auto mode (with `imap:`)

The import runs on the daily schedule. To run it immediately, call the
`eso.fetch_now` service (**Developer Tools → Actions**). It performs the
full flow: credential login, reads the one-time code over IMAP, submits it, and
imports statistics. Watch **Settings → System → Logs**.

### Manual mode (no `imap:`)

Omit the `imap:` block to drive login by hand. Services:

- `eso.start_login` — triggers ESO to email a code, fires an
  `eso_tfa_required` event, and raises a notification.
- `eso.submit_tfa_code` (`code`) — submits the code and imports data.

Example: prompt for the code on your phone and submit it.

```yaml
automation:
  - alias: ESO ask for TFA code
    trigger:
      - platform: event
        event_type: eso_tfa_required
    action:
      - action: notify.mobile_app_your_phone
        data:
          message: "Enter your ESO login code"
          data:
            actions:
              - action: "ESO_TFA_CODE"
                title: "Enter code"
                behavior: textInput
                textInputButtonTitle: "Submit"
                textInputPlaceholder: "6-digit code"

  - alias: ESO submit TFA code
    trigger:
      - platform: event
        event_type: mobile_app_notification_action
        event_data:
          action: "ESO_TFA_CODE"
    action:
      - action: eso.submit_tfa_code
        data:
          code: "{{ trigger.event.data.reply_text }}"
```

## Development

```bash
pip install -r requirements-test.txt
python -m pytest          # tests + coverage
python -m ruff check .    # lint
```

Tests cover the pure-logic modules (`form_parser`, `imap_client`, `eso_client`).
`__init__.py` is Home Assistant runtime glue and is exercised inside HA rather
than in unit tests.

## License

[MIT](LICENSE). This fork is distributed under MIT; it builds on the upstream
[`algirdasc/hass-eso`](https://github.com/algirdasc/hass-eso) project.
