# PyXaseco 1.5

PyXaseco is a Python-based server controller for TrackMania Nations Forever and
TrackMania United Forever. It builds on the familiar XAseco experience: records,
rankings, map management, voting, chat commands and an in-game HUD, with an
app-based structure that lets server owners choose what they need.

Use it for a straightforward racing server or extend it with RPG/Trial records,
checkpoint tools, community features and external integrations. The controller
runs alongside the dedicated server; it is not a replacement for the game server.

[App Guides](apps/README.md) | [Credits](APP_CREDITS.md) | [GitHub](https://github.com/nilakite2/PyXaseco) | [Discord](https://discord.gg/CwFNmzKX8G)

## Features

| Area | What PyXaseco Provides |
| --- | --- |
| Administration | Player moderation, access rights, map management, game settings and in-game administrative commands. |
| Records and rankings | Database-backed personal bests, local leaderboards, player statistics and server rankings. PB storage is independent of the displayed leaderboard limit. |
| External records | Optional Dedimania, RPG, Trial, Ultimania and WRMania providers, with record windows, submissions and shared HUD presentation. |
| Maps and discovery | Map lists, jukebox requests, TMX searches/downloads, map information and GPS/video links. |
| In-game interface | Records-Eyepiece widgets, ManiaKarma, menus, panels, live standings and an optional alternate scoretable. |
| Personal presentation | Persistent Classic/Modern UI selections, accent variants, custom templates and individual widget visibility. |
| Checkpoint tools | Live checkpoint positions, session bests and checkpoint/sector comparisons through apps such as CP Live and zTrack. |
| Community features | Voting, donations, quotes, timed announcements, curated GPS, sponsor banners and optional Discord integration. |
| Server-owner tools | App configuration, optional database backups, population statistics, integration-health information and verified file updates. |

Apps are selected per server. Optional integrations are not required for every
installation, and an unavailable external service does not need to disable
unrelated record providers.

## Apps And Customization

The core handles the server connection, events and shared runtime services. The
App Manager loads the apps selected in `apps.toml`; each app supplies its own
commands, services or interface elements. App guides describe the available
settings, commands, requirements and original authors.

- Keep the base apps and the dependencies required by your chosen loadout.
- Enable only the record providers, gameplay tools and integrations you want.
- Configure widgets, messages and supported app settings for each server.
- Let players select their own UI preset, or inherit the server's default.
- Run a separate controller instance and configuration for each dedicated server.

Browse the [complete app index](apps/README.md) for individual guides, including
[Local Records](apps/records_local/README.md), [UI](apps/ui/README.md),
[Platform UI](apps/platform_ui/README.md), [Trial Records](apps/records_trial/README.md),
[Mania Records](apps/records_wrmania/README.md) and [zTrack](apps/ztrack/README.md).

PyXaseco uses Python apps and TOML configuration rather than loading legacy PHP
plugins directly. Existing XAseco plugin functionality must be adapted as an app.

## Requirements

- A TrackMania Forever dedicated server with working XML-RPC access.
- Python 3.12 with pip, on Windows or Linux.
- A MariaDB/MySQL database and database user for the controller.
- The Python libraries pinned in [requirements.txt](requirements.txt).

External integrations require access to their respective services. Configure
only the apps you intend to use.

## Installation

1. Download and unpack PyXaseco into its own folder, normally `PyXaseco/` inside
   the dedicated-server directory.
2. Create a controller database/user, or back up the existing database before
   connecting it. The controller checks and creates supported tables/schema
   additions at startup; it does not create the database account for you.
3. Install the dependencies from the controller folder:

   ```powershell
   py -3.12 -m pip install -r requirements.txt
   ```

4. Copy `.env.example` to `.env` and enter the server connection, database and
   path settings. Set your MasterAdmin login in `config.toml` and review
   `adminops.toml`.
5. Review `apps.toml` and the enabled apps' configuration before starting.
   Some optional apps are enabled in the supplied loadout; keep only those
   appropriate for your server, together with their required dependencies.
6. Start the dedicated server, then start PyXaseco:

   ```powershell
   py -3.12 main.py
   ```

`PyXaseco.bat` is the supplied Windows launcher and can be adapted to your setup.
On Linux, use the Python 3.12 interpreter configured for your installation in
place of `py -3.12`. Run commands from the controller directory.

For debug logging:

```powershell
py -3.12 main.py --debug
```

Logs are written to `logfile.txt`.

## Configuration And Layout

```text
PyXaseco/
  apps/              App packages and their individual guides
  pyxaseco/          Core runtime and management services
  .env               Connection credentials and environment overrides
  .env.example       Configuration reference without live credentials
  apps.toml          Enabled/disabled app loadout
  config.toml        Core options, MasterAdmins and legacy connection settings
  settings.toml      Shared controller settings
  messages.toml      Chat messages and formatting
  adminops.toml      Administrator/operator lists
  bannedips.toml     Banned IP list
  requirements.txt   Pinned Python dependencies
  main.py            Controller entrypoint
  PyXaseco.bat       Windows launcher
```

Use `.env` for supported credentials/environment overrides. `config.toml`
remains part of the controller configuration and supports legacy connection
settings; it is not replaced by `.env`.

Where supplied, app settings live in `apps/<app_name>/app_defaults.toml`.
Individual guides document exceptions, including Trial Records' API constants
in `apps/records_trial/service.py`.

Use actual app-folder names in the loadout, for example `app/records_dedimania`,
`app/records_trial`, `app/platform_ui` and `app/ui`. See
[Apps Manager](apps/apps_manager/README.md) for dependencies and controls.

## Useful Commands

Commands for optional apps are available only when those apps are loaded.

| Command | Purpose |
| --- | --- |
| `/help`, `/helpall` | Show registered public commands. |
| `/server` | Server information and enabled-integration health. |
| `/recs`, `/pb` | Current-map local records and your saved personal best. |
| `/list`, `/jukebox` | Browse maps and manage map requests. |
| `/tmxinfo`, `/xlist` | TMX map information and searches. |
| `/karma`, `/karma details` | Map voting information and statistics. |
| `/uistyle list`, `/uistyle <id>` | Choose a persistent personal UI preset. |
| `/uistyle default` | Inherit the server's default UI preset. |
| `/style list` | Choose a legacy window style. |
| `/ztrack` | Checkpoint/sector comparison help. |
| `//apps` | MasterAdmin app management and supported configuration controls. |
| `//pyres` | Restart the controller to load copied Python changes. |

`//apps reload <app>` applies supported configuration reloads, not edited Python
source. Loadout changes also require a controller restart.

## Maintenance

Back up the controller, database and configuration before updating. Preserve
your `.env`, loadout, app defaults and any personally modified source files.
When using a manual copy-over package, keep its file paths and merge configuration
references rather than replacing server-specific settings. Finish copying all
related files before running `//pyres`.

Apps Manager also supports optional verified file updates with MasterAdmin
review, configuration backups and manual restart. This is not required to run
PyXaseco or to maintain it through ordinary file copies. See the
[updater guide](pyxaseco/management/UPDATER.md) for that workflow.

## Credits And License

Python adaptation and PyXaseco development: Nila / PyXaseco project.
Based on XAseco and community plugins; original authors are credited in the
[project credits](APP_CREDITS.md) and individual app guides.

See [LICENSE](LICENSE) and any app-specific notices for licensing details.
