# Core Plugins

Reserved for foundational controller plugins in v1.2.

Examples:

- `localdb`
- `rounds`
- `track`

`feature/rasp` intentionally does not live here anymore.

Current ownership split:

- `core/*` = foundational controller state
- `service/*` = optional shared data systems
- `feature/*` = gameplay/controller behavior bundles such as RASP

The active loadout is defined in `plugins.toml`.
