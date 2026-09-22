# PyXaseco v1.2-DEV Release

PyXaseco v1.2 is a Python-based server controller for TrackMania Forever.

It is built to cover the familiar XAseco-style server workflow while using a cleaner app-based runtime layout under the hood.

## What It Does

PyXaseco provides the usual controller responsibilities you would expect on a TrackMania Forever server:

- Server administration and moderation
- Local records and Dedimania
- TMX and jukebox
- Rankings, chat commands, and player utilities
- HUD and widget rendering through Records Eyepiece
- Optional integrations like Discord, public stats, karma, and more

## Project Layout

```text
PyXaseco_v1.2/
  apps/              Active app packages
  pyxaseco/          Core runtime
  apps.toml          Active app loadout
  config.toml        Core controller + TM server connection config
  settings.toml      Server/controller settings
  messages.toml      Chat/message strings
  adminops.toml      Admin/operator lists
  bannedips.toml     Banned IP list
  main.py            Entrypoint
  PyXaseco.bat       Windows launcher
```

## Active Loadout

The runtime loadout is defined in `apps.toml`.

That file decides which apps the controller loads on startup.

The active loadout includes app entries such as:

- `app/platform_core`
- `app/admin`
- `app/records_local`
- `app/dedimania`
- `app/tmx`
- `app/trial_records`
- `app/records_rpg`
- `app/rasp`
- `app/records_eyepiece`
- `app/platform_ui`
- `app/fufi_menu`

## Installation good old simple way
1. Download the files "Code -> Download ZIP".
2. Unpack inside of your root server folder where dedicated server is.
3. Install Python dependencies.
4. Copy `.env.example` to `.env` and update the environment values for your server, database, and optional integrations.
5. Attach existing Xaseco DB or import the base database schema.
6. Review config of `PyXaseco.bat` and start it.

## Python dependencies

```powershell
py -3.12 -m pip install -r requirements.txt
```

## Basic startup

Review `.env.example`, create your own `.env`, and update the values there.

Start the controller with:

```powershell
py -3.12 main.py
```

For debug logging:

```powershell
py -3.12 main.py --debug
```

Or update `PyXaseco.bat` as you see fit.

## Configuration

The main runtime files are:

- `config.toml`
- `apps.toml`
- `settings.toml`
- `messages.toml`
- `adminops.toml`
- `bannedips.toml`
- `.env`

App defaults are stored per app in:

- `apps/<app_name>/app_defaults.toml`

## Notes

- The controller writes logs to `logfile.txt`.
- Some apps depend on external services or APIs, such as Dedimania, TMX, Discord webhooks, or public stats endpoints.
