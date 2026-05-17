# PyXaseco v1.2

PyXaseco v1.2 is the structured controller branch for **TrackMania Forever**.

It keeps compatibility with the validated controller behavior (1.1-Stable), but reorganizes the runtime around:

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
- compatibility aliases for many legacy plugin import names
- active record services for:
  - local DB
  - Dedimania
  - Trial Records
  - RPG Records

What is still deferred:

- `panels/*.xml`
- `styles/*.xml`

## Active Runtime Files

- `config.toml`
- `plugins.toml`
- `settings.toml`
- `messages.toml`
- `plugin_defaults.toml`
- `adminops.toml`
- `bannedips.toml`
- `nations.toml`

## Active Loadout

The active loadout is defined in `plugins.toml`.

Current categories:

- `core/*`
- `service/*`
- `chat/*`
- `feature/*`
- `ui/*`
- `bridge/*`

## Installation

1. Create and activate a Python 3.12 environment.
2. Install dependencies from `requirements.txt`.
3. Copy or create:
   - `config.toml`
   - `plugins.toml`
   - `settings.toml`
   - `messages.toml`
   - `plugin_defaults.toml`
   - `adminops.toml`
   - `bannedips.toml`
   - `nations.toml`
4. Provide secrets in `.env` when needed.
5. Start the controller with `main.py`.

### Windows example

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
py -3.12 main.py config.toml
```

### Linux example

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3.12 main.py config.toml
```

### Debug mode

```bash
python3.12 main.py config.toml --debug
```

## Notes

- Active runtime config is TOML-first.
- `.env` is intended for credentials and environment-specific secrets.
- `plugin_defaults.toml` currently holds shared plugin-owned settings until later split-out work is done.
- If you are looking for the migration notes rather than the public overview, use `00README.md` and `..\pyxaseco_v1.2.md`.
