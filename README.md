# Arc Launcher for Home Assistant

Manage [Arc Launcher](https://github.com/meddouribadis/arclauncher) on your Android/Google TVs from Home Assistant:
see which layout each TV follows and when it last synced, sync or back up a TV, switch sharing and following, and
restore a layout from a file or from another TV.

It talks to the launcher's local control API (port 47474) on your network; nothing goes through the cloud.

## Requirements

- Arc Launcher with the local control API (API version 1), set as the home app on the TV.
  The API only answers while Arc Launcher runs as the home app.
- On the TV: **Settings > Backup & restore > Allow control from other apps** turned on.
  Turning it off unpairs every app, including Home Assistant.
- Home Assistant 2025.6 or newer.

## Installation

1. In HACS, open the menu > **Custom repositories**, add `https://github.com/Bluicie/ha-arc-launcher` as type
   **Integration**, and install **Arc Launcher**.
2. Restart Home Assistant.

## Setup

TVs with control turned on are found automatically (zeroconf `_arclauncher._tcp`) and show up under
**Settings > Devices & services** as discovered. You can also add one by hand with **Add integration > Arc Launcher**
and its IP address (or `.local` name; the TV refuses other host names).

Home Assistant then asks the TV for a pairing code: a 6-digit code appears on the TV for 2 minutes. Type it in to
finish. After 5 wrong codes pairing is blocked for a while. If the TV later stops accepting Home Assistant (for example
because control was turned off), Home Assistant asks you to pair again.

## Entities

Per TV:

| Entity | Type | What it does |
|---|---|---|
| Last sync | sensor (timestamp) | When the TV last checked the layout it follows |
| Sync status | sensor | `never`, `syncing`, `ok` or `error`; the attribute `last_error` holds the error |
| Following | sensor | Name of the TV this TV follows |
| Layout version | sensor (diagnostic) | Fingerprint of the current layout, with the number of sections and apps |
| Share layout | switch | Let other TVs follow this TV's layout |
| Automatic sync | switch | Let the TV check the followed layout by itself (at start and every 6 hours) |
| Automatic backup | switch | Let the TV write a backup file on the TV when its layout changes |
| Follow | select | Not following, or one of the other TVs in Home Assistant that share their layout |
| Sync now | button | Fetch and apply the followed layout now |
| Back up now | button | Write a timestamped backup file on the TV |
| Quick action | event | Fires when a quick-action button on the TV is pressed (only when the TV has buttons) |

The status is polled every 60 seconds.

## Quick actions

Put up to 6 buttons on the TV's status bar that run something in Home Assistant, such as "Movie night" or
"Lights off". Open the TV under **Settings > Devices & services > Arc Launcher**, choose **Configure**, add buttons
with a label (at most 24 characters), an icon and what to run (a scene, script or automation, or nothing), then
**Save**. Home Assistant sends them to that TV; each TV has its own buttons, and they are never part of a shared
layout.

Pressing a button calls a local webhook of Home Assistant, which then:
- turns on the scene or script, or triggers the automation;
- fires the event `arc_launcher_quick_action` with `device_id`, `action` (the button's id) and `label`;
- updates the TV's **Quick action** event entity, whose event type is the button's id. Use it as the trigger for your
  own automations (handy for buttons that run nothing themselves).

The TV calls Home Assistant on its local address (**Settings > System > Network**, local network URL); a plain-http
host name is replaced by Home Assistant's IP address, because the TV cannot always resolve it. The webhook only
accepts calls from the local network. Removing the integration, or disabling the TV in Home Assistant, removes the
buttons from the TV. Needs an Arc Launcher version with quick actions; older versions are left alone.

## Action `arc_launcher.restore_layout`

Applies an Arc Launcher settings file to one or more TVs. Give either `file` or `from_device`:

```yaml
action: arc_launcher.restore_layout
data:
  device_id: <TV device>
  file: arc-launcher/kids.json   # relative to the config folder
```

```yaml
action: arc_launcher.restore_layout
data:
  device_id: [<TV device>, <TV device>]
  from_device: <device of the TV to copy>
```

The response lists per TV how many categories, apps and settings were restored and which apps are missing on that TV.
Make a settings file with **Settings > Backup & restore** on the TV, or with the TV's web page.

## Blueprints

- **Sync when a TV turns on**: when the TV's media player turns on, wait 30 seconds and press Sync now.
  [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FBluicie%2Fha-arc-launcher%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Farc_launcher%2Fsync_when_tv_turns_on.yaml)
- **Nightly sync**: every night (default 03:00) press Sync now on the chosen TVs, and optionally Back up now.
  [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FBluicie%2Fha-arc-launcher%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Farc_launcher%2Fnightly_sync.yaml)

## Development

```bash
python -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
```

## License

MIT. The icon in `custom_components/arc_launcher/brand/` is the Arc Launcher app icon.
