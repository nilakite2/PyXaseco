# PyXaseco 1.0-Alpha

PyXaseco is a Python 3.12 controller for **TrackMania Forever** servers, inspired by XASECO and focused on practical parity for day-to-day server administration, records, widgets, chat commands, etc..

This public alpha includes the Python core, XML-based configuration, a broad plugin set.

## Status

This is an **stable Alpha release**.

It is intended for:
- private servers
- testing and validation
- feature parity checks against existing XASECO workflows
- plugin migration and iteration

It is not presented as a fully finished drop-in replacement for every historical XASECO setup.
But it integrates with existing .xml configs and past Xaseco DB instances.

## Highlights

- Python 3.12 async core
- TrackMania Forever dedicated server support via GBX Remote
- XML-driven configuration close to classic XASECO layouts
- MySQL/MariaDB-backed local records and player data
- Dedimania integration
- ManiaKarma integration
- TMX info integration
- RASP-style admin, jukebox, voting, and karma features
- split Records Eyepiece widgets and windows
- admin, player, records, stats, checkpoint, and utility chat commands

## Included components

### Core

- `main.py` — startup entry point
- `pyxaseco/core/aseco.py` — main controller
- `pyxaseco/core/gbx_client.py` — async GBX Remote client
- `pyxaseco/core/event_bus.py` — event dispatching
- `pyxaseco/core/plugin_loader.py` — plugin loading
- `pyxaseco/core/config.py` — XML config parsing
- `pyxaseco/models/` — player, challenge, record, server, and related models
- `pyxaseco/helpers.py` — common formatting and UI helpers

### Main plugin set

From `plugins.xml`, this alpha currently loads plugins such as:

- Local database
- Rounds support
- admin chat commands
- help / player / records / stats chat commands
- Dedimania
- TMX info
- track info
- checkpoints
- RASP base, jukebox, votes, nextmap, nextrank, chat, karma
- panels
- donate
- jfreu plugin
- CP live
- ManiaKarma
- Records Eyepiece
- ztrack
- fufi menu
- CPLL

## Runtime requirements

- Python **3.12**
- TrackMania Forever dedicated server
- MySQL or MariaDB for local database features

## Python dependencies

This release uses only five external Python packages directly in the codebase:

- `aiohttp`
- `aiomysql`
- `cryptography`
- `tzdata`
- `pycountry`

Install them with:

```bash
pip install -r requirements.txt
```

## requirements.txt

```txt
aiohttp==3.13.5
aiomysql==0.3.2
cryptography==46.0.7
tzdata==2026.1
pycountry==26.2.16
```

## Installation

1. Extract the release into your server controller directory.
2. Create and activate a Python 3.12 virtual environment.
3. Install Python dependencies.
4. Review and update the XML config files.
5. Start PyXaseco.

### Via PyXaseco.bat
Just run it. But make sure all .xml files wre updated.

### Via virtual environment:

### Windows example

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
py -3.12 main.py config.xml [--debug]
```

### Linux example

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3.12 main.py config.xml [--debug]
```


## Database setup

PyXaseco **does NOT auto-create database schema**.

You must import it manually before first run.

### Create database

```sql
CREATE DATABASE IF NOT EXISTS `pyxaseco`
CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;
```

### Import schema

```bash
mysql -u root -p pyxaseco < database/pyxaseco_default_schema.sql
```

## Configuration files

Main files included in this release:

- `config.xml`
- `plugins.xml`
- `adminops.xml`
- `bannedips.xml`
- `localdatabase.xml`
- `dedimania.xml`
- `mania_karma.xml`
- `records_eyepiece.xml`
- `rasp.xml`
- `matchsave.xml`
- `flexitime.xml`
- `fufi_menu_config.xml`

### Important setup items

Before first real use, update at least:

#### `config.xml`
- TM server login
- TM server password
- GBX port
- master admin login(s)
- optional message/style/panel preferences

#### `localdatabase.xml`
- MySQL server
- MySQL login
- MySQL password
- MySQL database name

#### Other plugin configs
Review optional plugin configs if you use them:
- `dedimania.xml`
- `mania_karma.xml`
- `records_eyepiece.xml`
- `plugins/jfreu/jfreu.config.xml`
- `plugins/jfreu/jfreu.vips.xml`
- `plugins/jfreu/jfreu.bans.xml`

## Running

Basic run:

```bash
python main.py config.xml
```

Debug mode:

```bash
python main.py config.xml --debug
```

PyXaseco writes logs to:

- console output
- `logfile.txt`

## Repository layout

```text
PyXaseco/
├── main.py
├── requirements.txt
├── README.md
├── config.xml
├── plugins.xml
├── localdatabase.xml
├── dedimania.xml
├── mania_karma.xml
├── records_eyepiece.xml
├── pyxaseco/
│   ├── core/
│   └── models/
├── database/
│   └── pyxaseco_default_schema.sql
├── plugins/
│   ├── plugin_localdatabase.py
│   ├── plugin_dedimania.py
│   ├── plugin_mania_karma.py
│   ├── plugin_rasp.py
│   ├── plugin_tmxinfo.py
│   ├── plugin_ztrack.py
│   ├── plugin_records_eyepiece.py
│   └── records_eyepiece/
├── panels/
└── styles/
```

## Notes for users coming from XASECO

- XML configuration is intentionally familiar.
- Plugin naming is Python-based in this release.
- This build targets **TMF**, not a broad multi-title compatibility matrix.
- Some plugins are close ports, while others are practical Python-native rewrites shaped around the PyXaseco core.

## Known alpha expectations

Expect normal alpha-release realities:
- some plugins are more mature than others
- parity work may still be ongoing in edge cases
- UI/window fidelity may continue to evolve
- some optional legacy subsystems may be absent or intentionally deferred

## Contributing / testing

Useful feedback includes:
- reproducible errors
- plugin-specific regressions
- ManiaLink/UI mismatches
- Dedimania / ManiaKarma / TMX integration issues
- database schema or migration issues
- differences versus XASECO behavior that matter in real servers

## Credits & Notes

PyXaseco is inspired by and partially derived from the XAseco project.

Original project:
https://www.xaseco.org/

This project reimplements functionality in Python and adapts it for modern usage.

Parts of this project were developed with assistance from AI tools such as:

- ChatGPT (GPT-5.3)
- Claude (Sonnet 4.6)

## License

GNU GPL v3. See LICENSE file.
