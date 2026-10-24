# Platform Core

## Purpose

Provides shared database, player/map persistence, round flow, checkpoint tracking,
chat logging, donations and low-level gameplay services used by other apps.

## Commands

| Command | Purpose |
| --- | --- |
| `/track` | Show information about the current map. |
| `/playtime`, `/time` | Show playing-time/current-time information. |
| `/nextmap` | Show the next map. |
| `/chatlog` | Show recent chat history. |
| `/cptms`, `/sectms` | Show record checkpoint/sector times. |
| `/donate <amount>` | Donate server coppers where supported. |
| `/song`, `/mod` | Show the map's song/mod information. |

Administrative round-points control is `//rpoints`, routed through Admin rather
than a separately registered public `/rpoints` command.

## Configuration

Keep `app/platform_core` in the base loadout. Use `.env` for connection credentials,
`settings.toml` for shared controller/database behavior and `app_defaults.toml`
for supported app-owned defaults. Database credentials and schema permissions
must match the configured MariaDB/MySQL installation.

## Changes And Limits

- Related legacy plugins are grouped behind shared services, so apps do not need
  their own direct imports of another optional app's database implementation.
- Supported schema additions are checked/applied during startup; a controller
  database is still required. Creating a database/account is a separate setup step.
- Donations depend on TMF account/server capabilities; displaying a command does
  not bypass game restrictions or create coppers.
- `/mod` reports map information; ForceMods is the separate optional mod manager.

## Credits

Localdatabase: Florian Schnell, with updates by Xymph.
XAseco rounds, track, song/mod, chatlog, checkpoints, donations and round points: Xymph.
RASP: Xymph and AssemblerManiac. FreeZone: NADEO.
PyXaseco adaptation: Nila / PyXaseco project.
