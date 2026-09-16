# KSLive for Home Assistant

An unofficial HACS integration for active [KSLive](https://kslive.com.au) subscribers. It finds the KSLive audio broadcast and recent audiocasts, resolves a fresh subscriber stream, and sends it to one or more Home Assistant media players.

## Features

- Home Assistant UI login using your KSLive subscriber email and password.
- The password is exchanged for short-lived access/refresh tokens and is never stored.
- Automatic token refresh and Home Assistant reauthentication when required.
- Audio status sensor with current, upcoming, and latest-recording metadata.
- **Play audio** button for the live show (or latest available recording).
- `kslive.play` service for dashboards and automations, including an optional content ID and speaker override.
- Diagnostics redact authentication tokens and never expose signed playback URLs.

## Install with HACS

Until this repository is listed in the HACS default store:

1. In HACS, open **Integrations**.
2. Open the menu and choose **Custom repositories**.
3. Add this repository as category **Integration**.
4. Search for **KSLive**, download it, and restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration → KSLive**.
6. Sign in and select the target speaker(s). You can change them later with **Configure**.

For a manual installation, copy `custom_components/kslive` into Home Assistant's `config/custom_components` directory and restart Home Assistant.

## Using it

Press **KSLive Play audio**, or call:

```yaml
action: kslive.play
data:
  media_players:
    - media_player.living_room
```

To play a specific recording, also provide its `content_id`. IDs for the current show, next show, and latest recording are exposed as attributes on the **KSLive Audio status** sensor.

The target speaker must support HTTPS HLS/AAC playback. Some cast devices require Home Assistant and the speaker to have working internet access and correct DNS/time settings.

## Security and compatibility

This project is not affiliated with KSLive, King Kyle Group, or Uscreen. It is intended only for subscribers accessing content their account is authorized to play. It does not remove DRM, bypass subscription checks, or redistribute media.

KSLive uses Uscreen's subscriber app API and short-lived signed media links. Those private app endpoints can change without notice, so a future KSLive app update may require an integration update.
