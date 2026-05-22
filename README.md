# PyXaseco v1.2

PyXaseco v1.2 is the structured controller branch for **TrackMania Forever**.

It keeps parity with the validated controller behavior, but reorganizes the runtime around:

- TOML-first config
- category-based plugin naming
- clearer ownership boundaries
- incremental migration instead of a full rewrite

## Status

This branch is usable for active testing and staged rollout work.

What is already in place:

- Python 3.12 async controller core
- TOML-based active runtime config
- active plugin tree split into `core`, `service`, `chat`, `feature`, `ui`, and `bridge`
- TOML-based active panel/style catalogs in `panels/panels.toml` and `styles/styles.toml`
- active record services for:
  - local DB
  - Dedimania
  - Trial Records
  - RPG Records

## Active Runtime Files

- `config.toml`
- `plugins.toml`
- `settings.toml`
- `messages.toml`
- `plugin_defaults.toml`
- `adminops.toml`
- `bannedips.toml`
- `nations.toml`
- `panels/panels.toml`
- `styles/styles.toml`

## Active Loadout

The active loadout is defined in `plugins.toml`.

Current categories:

- `core/*`
- `service/*`
- `chat/*`
- `feature/*`
- `ui/*`
- `bridge/*`

## Installation good old simple way
1. Download the files "Code -> Download ZIP".
2. Unpack inside of your root server folder where dedicated server is.
3. Install Python dependencies.
4. Review and update the XML config files (config.xml, localdatabase.xml, dedimania.xml, maniakarma.xml).
5. Attach existing Xaseco DB or import the base database schema.
6. Review config of "PyXaseco.bat" and start it.

### Debug mode

```bash
py -3.12 main.py config.toml --debug
```

## Notes

- Active runtime config is TOML-first.
- `.env` is intended for credentials and environment-specific secrets.
- `plugin_defaults.toml` currently holds shared plugin-owned settings until later split-out work is done.
