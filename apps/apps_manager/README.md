# Apps Manager

## Purpose

Provides loadout, dependency and app-configuration management. The in-game entry
point is routed through Admin; this app supplies the management service.

## Commands

All actions below require MasterAdmin access.

| Command | Purpose |
| --- | --- |
| `//apps` | Open Apps Manager. |
| `//apps list`, `//apps status <app>` | Review availability and state. |
| `//apps config <app>` | Edit supported app settings. |
| `//apps reload <app>` | Reload supported configuration, not Python source. |
| `//apps enable <app>`, `//apps disable <app>` | Change the loadout for the next restart. |
| `//apps add <app>`, `//apps remove <app>` | Restore/remove eligible optional apps using managed local storage. |

## Configuration

The loadout is `apps.toml`. Each app supplies its own metadata and, where present,
`app_defaults.toml` settings schema. This app has no separate defaults file.

## Changes And Limits

- Config and Reload are offered only for installed, enabled, loaded apps.
- An app omitted from the enabled loadout is not active even if `disabled = []`.
- Missing app files are reported as missing; no automatic download button exists.
- Managed removal uses `apps/00removed`
- Dependency checks and validation prevent unsupported loadout/configuration edits.
  A restart remains necessary for loadout and Python-source changes.

## Credits

Nila / PyXaseco project.
