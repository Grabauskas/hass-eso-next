# Setting up a Google (Gmail) account for ESO OTP login

ESO's self-service portal (`mano.eso.lt`) now emails a one-time 6-digit code on
**every** login. In **auto mode** the integration reads that code itself over
IMAP. This guide walks you through creating and configuring a Gmail account so
Home Assistant can read those codes — and nothing else.

> **Why a dedicated account?** IMAP access gives Home Assistant the ability to
> read every message in the mailbox. You do **not** want to hand your personal
> inbox to a home automation server. Instead, create a throwaway Gmail account
> that only ever receives ESO login codes (via a forwarding filter on your real
> inbox). If its app password ever leaks, the blast radius is "someone can read
> your ESO OTP emails" — not your whole life.

---

## Overview

You will:

1. Create a new, dedicated Google account.
2. Turn on 2-Step Verification (required before app passwords exist).
3. Generate a 16-character **app password** for IMAP.
4. Confirm IMAP is enabled in Gmail.
5. Forward only ESO's emails from your real inbox to the new account.
6. Put the host / username / app password into the `eso:` → `imap:` config.

Total time: ~10 minutes.

---

## Step 1 — Create a dedicated Google account

1. Open an **incognito / private browser window** (so you don't disturb any
   account you're already signed into).
2. Go to <https://accounts.google.com/signup>.
3. Fill in the form:
   - **First / last name:** anything, e.g. `HA` / `ESO`.
   - **Username:** pick something dedicated, e.g.
     `myhouse.eso.otp@gmail.com`. Write the full address down — you'll need it.
   - **Password:** generate a strong, unique password and store it in your
     password manager.
4. Complete phone / recovery verification if Google asks (it usually does for
   new accounts).
5. Accept the terms and finish. You now have a clean mailbox.

> You will **not** type this Google password into Home Assistant. HA uses a
> separate *app password* created in Step 3.

---

## Step 2 — Enable 2-Step Verification

App passwords only exist once 2-Step Verification is on.

1. While signed into the new account, go to
   <https://myaccount.google.com/security>.
2. Under **"How you sign in to Google"**, click **2-Step Verification**.
3. Click **Get started** and follow the prompts (confirm with the phone number
   you registered, or add an authenticator app).
4. When finished, the 2-Step Verification status should read **On**.

---

## Step 3 — Generate an app password

This 16-character password is what Home Assistant uses to log in over IMAP.
Gmail no longer allows plain-account-password IMAP login.

1. Go directly to <https://myaccount.google.com/apppasswords>.
   (If the page says it's unavailable, 2-Step Verification from Step 2 isn't
   fully enabled yet — finish that first.)
2. You may be asked to re-enter your account password.
3. In the **App name** box, type something recognizable, e.g.
   `Home Assistant ESO`.
4. Click **Create**.
5. Google shows a **16-character password** in a yellow box, usually grouped as
   four blocks of four (e.g. `abcd efgh ijkl mnop`).
6. **Copy it now** — Google will not show it again. You can paste it with or
   without spaces; spaces are ignored. Store it in your password manager.

> If you ever rotate or lose this, just delete it here and generate a new one,
> then update your Home Assistant config.

---

## Step 4 — IMAP access (already on)

IMAP is **always enabled** on Gmail now — Google removed the old "Enable IMAP"
radio button. There's nothing to switch on. If you open
**Settings** → **See all settings** → **Forwarding and POP/IMAP**, the
**IMAP access** section just shows behavior options (Auto-Expunge, what happens
on delete, folder size limits). You can leave all of those at their defaults:

- **Auto-Expunge on** (default) — fine.
- **Archive the message** (default) — fine.
- **Do not limit the number of messages** (default) — fine.

Nothing here needs changing for this integration; the defaults work. Just note
the server details you'll need for the config:

| Setting  | Value             |
|----------|-------------------|
| Host     | `imap.gmail.com`  |
| Port     | `993` (SSL)       |
| Username | the full Gmail address (e.g. `myhouse.eso.otp@gmail.com`) |
| Password | the **app password** from Step 3 |

---

## Step 5 — Forward only ESO emails to the dedicated account

ESO sends the code to whatever email is registered on your ESO account — most
likely your personal inbox. Rather than changing your ESO account email, set up
a filter that auto-forwards **only** ESO's messages to the new mailbox.

Do this in **your personal Gmail** (the one ESO emails today):

1. In your personal Gmail, go to **Settings** → **Forwarding and POP/IMAP** →
   **Add a forwarding address**, and add your new account
   (`myhouse.eso.otp@gmail.com`). Google emails a confirmation link to the new
   account — open that mailbox and click it.
2. Back in your personal Gmail, click the **search box filter icon** (sliders)
   to create a filter. In the **From** field enter:

   ```
   savitarna@eso.lt
   ```

3. Click **Create filter**.
4. Tick **Forward it to:** and choose your new account from the dropdown.
   (Optionally also tick **Mark as read** / **Skip the Inbox** to keep your own
   inbox tidy.)
5. Click **Create filter** to save.

From now on, every ESO login code lands in the dedicated mailbox within
seconds, and Home Assistant reads it from there.

> **Using a non-Gmail personal inbox?** Any provider that supports rule-based
> forwarding works — set a rule "from `savitarna@eso.lt` → forward to the new
> Gmail." The destination just has to be the dedicated Gmail you set up above.
>
> **Alternative:** if you don't mind it, you can simply change the email on your
> ESO account to the dedicated address directly, and skip the forwarding filter.

---

## Step 6 — Configure Home Assistant

Add the `imap:` block to your `eso:` configuration in `configuration.yaml`,
using the values from Step 4:

```yaml
eso:
  username: your_eso_username      # ESO portal login
  password: your_eso_password      # ESO portal password
  imap:
    host: imap.gmail.com
    port: 993
    username: myhouse.eso.otp@gmail.com   # the dedicated Gmail address
    password: "abcdefghijklmnop"          # the 16-char app password (no spaces)
  objects:
    - name: My House
      id: 123456
```

Restart Home Assistant. On the next scheduled run (or when you trigger it), the
integration logs into ESO, waits for the code email to arrive in the dedicated
mailbox, reads it, and completes the login automatically.

> **Keep the app password out of plain text where you can.** Use Home
> Assistant `secrets.yaml`:
>
> ```yaml
> # secrets.yaml
> eso_imap_password: abcdefghijklmnop
> ```
>
> ```yaml
> # configuration.yaml
>     password: !secret eso_imap_password
> ```

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| `apppasswords` page is unavailable | 2-Step Verification isn't fully on (Step 2). |
| Login fails with "Invalid credentials" over IMAP | You used the Google account password instead of the **app password** (Step 3), or there's a stray space — paste it without spaces. |
| Code never arrives in the dedicated mailbox | The forwarding filter (Step 5) isn't matching. Confirm the **From** is `savitarna@eso.lt` and that you clicked the confirmation link Google sent to the new account. |
| IMAP connection refused / times out | Confirm host `imap.gmail.com` and port `993` (SSL). IMAP itself is always on in Gmail, so the cause is almost always wrong host/port or a network/firewall block. |
| Code is read but login still fails | The code may have arrived outside the 15-minute window, or an old email matched. Trigger a fresh login so a new code is sent. |

---

## Security notes

- The dedicated account should **only** ever contain ESO OTP emails. Don't use
  it for anything else.
- The app password grants mailbox read access — treat it like a credential.
  Store it in a password manager / `secrets.yaml`, never commit it to git.
- You can revoke access at any time from
  <https://myaccount.google.com/apppasswords> without changing your main
  account password.
- ESO will never ask you to share the code. This setup keeps the code flowing
  to a machine, not exposing it to anyone.
