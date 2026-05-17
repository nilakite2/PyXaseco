# PyXaseco 1.0 Alpha

PyXaseco is a Python 3.12 controller for **TrackMania Forever** servers, inspired by XAseco and built around practical day-to-day server administration, records, widgets, RASP-style map flow, and XML-driven configuration.

This repository snapshot is a **validated alpha pack**, not just an early proof of concept. It includes the Python core, the current XML config set, a working default plugin loadout, and optional Discord-side integrations.

## Status

This is an **alpha release with a validated baseline**.

It is intended for:
- private and community TMF servers
- migration from older XAseco-style setups
- plugin parity testing
- day-to-day real server use with the included loadout

It is not presented as a perfect one-size-fits-all drop-in for every historical XAseco installation, especially because real server setups vary a lot: some admins run a very minimal loadout, while others enable nearly everything at once.

## Highlights

- Python 3.12 async core
- TrackMania Forever dedicated server support via GBX Remote
- XML-driven configuration close to classic XAseco layouts
- MySQL/MariaDB-backed local records and player data
- Dedimania integration
- ManiaKarma integration
- TMX info integration
- RASP-style admin, jukebox, nextmap, voting, and karma features
- Records Eyepiece widget/window suite
- CP Live and banner widgets
- optional Discord webhook mirroring
- optional standalone Discord chat bot bundle

## Default plugin loadout

The included [plugins.xml](plugins.xml) enables a broad practical set by default, including:

- local database
- admin chat commands
- help, player, records, stats, and server chat commands
- Dedimania
- TMX info
- checkpoints
- RASP base, jukebox, votes, nextmap, nextrank, and chat helpers
- panels and donate support
- JFreu
- Records Eyepiece
- CP Live
- banner widget
- ManiaKarma
- FuFi menu
- Discord webhook mirroring

Some optional plugins are shipped but left disabled by default, such as:
- BestSecs
- BestCPs
- Freezone
- FlexiTime
- STALKER tools

For the pack-oriented plugin status sheet, see [00README.md](00README.md).

## Runtime requirements

- Python **3.12**
- TrackMania Forever dedicated server
- MySQL or MariaDB for local database features

## Python dependencies

This pack directly uses a small dependency set:

- `aiohttp`
- `aiomysql`
- `cryptography`
- `tzdata`
- `pycountry`

Install them with:

```bash
pip install -r requirements.txt
```

## Installation good old simple way
1. Download the files "Code -> Download ZIP".
2. Unpack inside of your root server folder where dedicated server is.
3. Install Python dependencies.
4. Review and update the XML config files (config.xml, localdatabase.xml, dedimania.xml, maniakarma.xml).
5. Attach existing Xaseco DB or import the base database schema.
6. Review config of "PyXaseco.bat" and start it.

## Installation with .venv

1. Extract the pack into your server controller directory.
2. Create and activate a Python 3.12 virtual environment.
3. Install Python dependencies.
4. Review and update the XML config files (config.xml, localdatabase.xml, dedimania.xml, maniakarma.xml).
5. Attach existing Xaseco DB or import the base database schema.
6. Start PyXaseco.

### Windows example

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
py -3.12 main.py config.xml
```

### Linux example

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3.12 main.py config.xml
```

### Debug mode

```bash
python main.py config.xml --debug
```

## Database setup

The pack still ships the base schema in:
- `database/pyxaseco_default_schema.sql`

Recommended setup is still:
1. create the database
2. import the base schema
3. let PyXaseco perform its normal startup checks and repairs

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

### Important note

Compared with earlier alpha snapshots, the current controller does more automatic structure maintenance than before:
- startup checks/repairs for controller-owned tables
- some charset widening/repair where needed
- extra challenge metadata support through `challenges_extra`

That makes upgrades and reuse of older XAseco-style databases much smoother. In practice, this pack has already been validated successfully against multiple older XAseco database instances without needing a fresh rebuild. For brand-new installs, importing the shipped schema is still the cleanest starting point, but existing XAseco-style databases are a realistic and supported migration path.

## Configuration files

Main files included in this pack:

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
- `discord_webhook.xml`

Before first real use, update at least:

### `config.xml`

- TM server login
- TM server password
- GBX port
- master admin login(s)
- optional message/style/panel preferences

### `localdatabase.xml`

- MySQL server
- MySQL login
- MySQL password
- MySQL database name

### Optional plugin configs

Review these if you use the related plugins:
- `dedimania.xml`
- `mania_karma.xml`
- `records_eyepiece.xml`
- `discord_webhook.xml`
- `plugins/jfreu/jfreu.config.xml`
- `plugins/jfreu/jfreu.vips.xml`
- `plugins/jfreu/jfreu.bans.xml`

## Discord integrations

### Outbound webhooks

The pack includes:
- [plugin_discord_webhook.py](plugins/plugin_discord_webhook.py)
- [discord_webhook.xml](discord_webhook.xml)

This handles one-way mirroring from PyXaseco to Discord, including:
- admin logs
- player chat
- joins/leaves
- new challenge notifications
- warnings/errors

### Optional Discord bot

The pack also includes:
- [DiscordBot-optional](DiscordBot-optional)

That bot is separate from the controller and is intended for Discord-to-server chat bridging using commands like:
- `-tm1 hello world`

See its local documentation here:
- [DiscordBot-optional/README.md](DiscordBot-optional/README.md)

## Repository layout

```text
PyXaseco/
|-- main.py
|-- requirements.txt
|-- README.md
|-- 00README.md
|-- config.xml
|-- plugins.xml
|-- localdatabase.xml
|-- dedimania.xml
|-- mania_karma.xml
|-- records_eyepiece.xml
|-- discord_webhook.xml
|-- pyxaseco/
|   |-- core/
|   `-- models/
|-- database/
|   `-- pyxaseco_default_schema.sql
|-- plugins/
|   |-- plugin_localdatabase.py
|   |-- plugin_dedimania.py
|   |-- plugin_mania_karma.py
|   |-- plugin_rasp.py
|   |-- plugin_tmxinfo.py
|   |-- plugin_records_eyepiece.py
|   |-- plugin_cplive_v3.py
|   |-- plugin_banner.py
|   |-- plugin_bestfinishes.py
|   `-- ...
|-- DiscordBot-optional/
|-- panels/
`-- styles/
```

## Notes for users coming from XAseco

- XML configuration is intentionally familiar.
- The project targets **TMF** rather than a broad multi-title compatibility matrix.
- Some plugins are close ports, while others are practical Python rewrites shaped around the PyXaseco core.
- The shipped plugin names are Python-native, even when the feature ancestry comes from older PHP plugin names.

## Known alpha expectations

This pack is much further along than a blank alpha skeleton, but normal alpha realities still apply:
- some optional plugins are more mature than others
- niche parity edge cases can still show up
- non-default loadouts need their own testing
- ManiaLink/UI fidelity is still an area where small fixes may continue over time

## Contributing / testing

Useful feedback includes:
- reproducible errors
- plugin-specific regressions
- ManiaLink/UI mismatches
- Dedimania / ManiaKarma / TMX integration issues
- database schema or migration issues
- differences versus XAseco behavior that matter in real servers

## Credits

PyXaseco is inspired by and partially derived from the XAseco project.

Original project:
- [xaseco.org](https://www.xaseco.org/)

PyXaseco is also listed on the official XAseco resources page:
- https://links.xaseco.org/resources.php#others

Thanks to the original XAseco developers for including it.

This project reimplements and adapts XAseco-style functionality in Python for modern TMF server usage.

Parts of this project were developed with assistance from AI tools such as:
- ChatGPT (GPT-5.3 & 5.4)
- Claude (Sonnet 4.6)

## License

GNU GPL v3. See `LICENSE`.
