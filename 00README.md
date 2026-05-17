# PyXaseco v1.2 Internal Notes

This file is the quick internal status sheet for `PyXaseco_v1.2`.

Use it for:

- current active loadout
- config ownership
- deferred areas not yet migrated

## Scope

This branch is the structured successor to `_validated_pack`.

It already uses:

- Python 3.12
- TOML-first active runtime config
- category-based plugin naming
- compatibility aliases for legacy plugin imports where still needed

## Source of Truth

Active runtime files:

- `config.toml`
- `plugins.toml`
- `settings.toml`
- `messages.toml`
- `plugin_defaults.toml`
- `adminops.toml`
- `bannedips.toml`
- `nations.toml`

Active loadout comes from:

- `plugins.toml`

Deferred second-pass config still left as XML:

- `panels/*.xml`
- `styles/*.xml`

Everything under `disabled/` is also still treated as deferred.

## Active Loadout

### Core

- `core/localdb`
- `core/rounds`
- `core/track`

### Services

- `service/tmx`
- `service/dedimania`
- `service/trial_records`
- `service/records_rpg`

### Chat

- `chat/admin`
- `chat/help`
- `chat/records`
- `chat/records2`
- `chat/recrels`
- `chat/dedimania`
- `chat/players`
- `chat/players2`
- `chat/wins`
- `chat/laston`
- `chat/lastwin`
- `chat/stats`
- `chat/server`
- `chat/songmod`
- `chat/me`

### Features

- `feature/rasp`
- `feature/rasp_jukebox`
- `feature/rasp_chat`
- `feature/rasp_nextmap`
- `feature/rasp_nextrank`
- `feature/rasp_votes`
- `feature/jfreu`
- `feature/cplive`

### UI

- `ui/style`
- `ui/panels`
- `ui/records_eyepiece`
- `ui/banner`

### Bridges

- `bridge/public_stats`
- `bridge/server_admin_bridge`

## Deferred / Not Active

Deferred examples:

- Discord bridge extras
- checkpoint extras
- bestsecs / bestcps / bestfinishes family
- FreeZone / FlexiTime
- FuFi menu
- ManiaKarma
- Winner Anthem
- ZTrack / CPLL

These sit under `disabled/` until they get the same restructuring pass.

## Current Design Rule

The important rule for this branch is:

- one behavior should have one owner

Examples:

- record services belong in `service/*`
- RASP flow belongs in `feature/*`
- widgets belong in `ui/*`
- publishing belongs in `bridge/*`

## Practical Reminder

If something looks wrong between notes and runtime:

- trust the live files in `plugins/`, `pyxaseco/`, and the TOML files first
- treat this file as a guide, not the authoritative runtime parser
