# Pushover Advanced for Home Assistant

A custom Home Assistant integration for [Pushover](https://pushover.net) that
exposes the full Messages API — everything the built-in core `pushover`
integration leaves out:

- Priorities `-2` to `2`, including **emergency priority** with `retry`/`expire`
  and a callback URL
- Sounds, URLs with titles, HTML/monospace formatting, TTL
- **Tags**, so a batch of emergency-priority messages can later be **cancelled
  in bulk** with `cancel_by_tag`
- **Cancel by receipt**, to stop an in-flight emergency alert as soon as it's
  handled
- Looking up a receipt's acknowledgement/delivery status
- File and base64 attachments
- Multiple Pushover accounts/applications side by side
- Optional **per-device end-to-end AES encryption**, so Pushover's servers
  and the Apple/Google push transport only ever see ciphertext

A simple `notify.send_message`-compatible entity is also provided for basic
automations, using each account's configured defaults.

## Installation

### HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=sp32087&repository=ha-pushover&category=integration)

This repository ([`sp32087/ha-pushover`](https://github.com/sp32087/ha-pushover))
isn't in the default HACS store, so it needs to be added as a custom
repository first:

1. Click the badge above (opens HACS directly to this repository), **or**
   add it manually: HACS → the **⋮** menu (top right) → **Custom
   repositories** → paste `https://github.com/sp32087/ha-pushover` →
   category **Integration** → **Add**.
2. Find **Pushover Advanced** in HACS and click **Download**.
3. Restart Home Assistant.
4. Go to **Settings → Devices & Services → Add Integration** and search for
   **Pushover Advanced** (see [Setup](#setup) below).

### Manual

Copy `custom_components/pushover_advanced` from this repository into your
Home Assistant `config/custom_components/` directory and restart Home
Assistant.

## Setup

Settings → Devices & Services → Add Integration → **Pushover Advanced**.
You'll need:

- Your Pushover **application token** (create one at
  https://pushover.net/apps/build)
- Your Pushover **user or group key**

The integration validates both against Pushover before creating the entry.
You can add it multiple times for multiple applications/accounts.

Open the integration's **Configure** dialog to set sending defaults (default
device, priority, sound, TTL, emergency retry/expire) and to register
per-device encryption secrets.

**Device names, group members, and sounds are pulled live from your
account** wherever the options dialog needs them (device/sound dropdowns
still accept a custom value if you'd rather type one):

- Device names come from `/1/users/validate.json`, which lists the devices
  registered to a plain user key.
- If your configured key is a **group** key rather than a user key, the
  integration also queries `/1/groups/{group}.json` and adds each member's
  device to the same dropdown (Pushover doesn't expose a registry of your
  *group names* beyond that one group's own name/member list — there's no
  "list all my groups" endpoint, so you still need to know which group key
  you're using).
- Sounds come from `/1/sounds.json`, so paid/custom sounds on your account
  show up automatically, not just the built-in set.

Both lookups are best-effort: if Pushover is unreachable when you open the
dialog, the fields fall back to a plain text box / a hardcoded sound list
rather than blocking you.

## Services

### `pushover_advanced.send_message`

The primary way to use this integration — every field maps directly to a
Pushover Messages API parameter. See `services.yaml` (rendered in the
Developer Tools → Actions UI) for the full field list.

**The `device` and `sound` fields render as an actual dropdown**, not free
text: whenever an account is set up (or reloaded), the integration fetches
the current device names and sound catalog for every configured account and
patches them into the service description, so the Developer Tools and
automation editor UI list them as selectable options (still with "custom
value" enabled, so a device or sound added on Pushover's side since the
last reload can still be typed in). If Pushover is unreachable at setup
time, these fields just fall back to plain text - `send_message` itself is
unaffected either way. Example:

```yaml
action: pushover_advanced.send_message
data:
  message: "The garage door has been open for 10 minutes."
  title: "Garage door"
  priority: 2
  retry: 60
  expire: 3600
  sound: siren
  device: garage_phone
  tags:
    - garage-door
    - security
```

The response contains `status`, `request`, and — for `priority: 2` — a
`receipt` you can use with the two services below.

### `pushover_advanced.cancel_receipt`

Stop retrying/notifying for a single emergency-priority message:

```yaml
action: pushover_advanced.cancel_receipt
data:
  receipt: "{{ trigger.event.data.receipt }}"
```

### `pushover_advanced.cancel_by_tag`

Stop retrying/notifying for **every pending** emergency-priority message
that was sent with a given tag — useful when one automation fires several
emergency alerts (e.g. to multiple devices) and a single acknowledgement
elsewhere should silence all of them:

```yaml
action: pushover_advanced.cancel_by_tag
data:
  tag: security
```

### `pushover_advanced.get_receipt`

Look up whether an emergency message has been acknowledged, expired, or
called back (returns response data — use it in a template or an automation
condition):

```yaml
action: pushover_advanced.get_receipt
data:
  receipt: "{{ my_receipt }}"
response_variable: receipt_status
```

If you have more than one Pushover Advanced account configured, pass
`config_entry_id` on any of the above to pick which one to use.

## End-to-end encryption

Pushover's official apps support an optional mode where each device
generates its own random 256-bit secret (shown in-app as a 64-character hex
string) and shares it with whatever is sending it notifications. The sender
then encrypts the message before it ever reaches Pushover's servers, so
neither Pushover nor Apple/Google's push transport can read the content —
only the receiving device, using the matching secret, can decrypt it.

To use it here:

1. In the Pushover app, enable end-to-end encryption for a device and copy
   its secret.
2. In this integration's options, choose **Add a device encryption key**,
   and enter the device name (exactly as registered with Pushover) and its
   secret. The secret is round-trip tested before being saved.
3. Call `send_message` with `encrypt: true` and `device` set to **only**
   that one device — encryption is inherently per-device, so a message
   encrypted for one device's key can't be broadcast to others.

```yaml
action: pushover_advanced.send_message
data:
  message: "Front door unlocked"
  device: my_phone
  encrypt: true
```

The scheme used (`custom_components/pushover_advanced/crypto.py`) is
AES-256-CBC with PKCS7 padding and an HMAC-SHA256 authentication tag,
following Pushover's own description of the feature: a fresh random IV
per field, `base64(iv || ciphertext || hmac)` sent in place of the
plaintext `message`/`title` values, with `encrypted=1` set on the request.

**Caveat:** Pushover does not publish a formal machine-readable spec for
this feature, and this implementation could not be validated end-to-end
against a live encrypted device registration while it was written (network
access to pushover.net was unavailable in the development environment).
Before relying on this for anything sensitive, register a real
end-to-end-encrypted device, send it a test message with `encrypt: true`,
and confirm it decrypts correctly in the Pushover app. Please open an issue
if you find the wire format needs adjustment.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r tests/requirements.txt
pytest
```

The test suite covers the API client and the encryption module directly
(pure Python, no running Home Assistant instance required) by stubbing out
the handful of Home Assistant symbols referenced at import time — see
`tests/conftest.py`.
