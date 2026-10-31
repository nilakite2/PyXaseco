# Apps Manager

## Purpose

Manages the app loadout, supported app configuration and verified file updates.
Commands are routed through Admin and restricted to MasterAdmins.

## Commands

| Command | Purpose |
| --- | --- |
| `//apps`, `//apps list` | Open Apps Manager. |
| `//apps status <app>` | Show availability and state. |
| `//apps config <app>` | Edit supported settings for an enabled, loaded app. |
| `//apps reload <app>` | Reload supported configuration, not Python source. |
| `//apps enable <app>`, `//apps disable <app>` | Change the loadout for the next restart. |
| `//apps add <app>`, `//apps remove <app>` | Restore/remove eligible apps using local managed storage. |
| `//apps updates` | Check matching signed GitHub and website catalogues. |
| `//apps download <package>` | Download and verify a controller or optional-app ZIP. |
| `//apps review <package>`, `//apps update <package>` | Review proposed file changes. |
| `//apps update <package> confirm` | Back up and copy, preserving modified code. |
| `//apps update <package> force confirm` | Also replace modified official code after backup. |

## Configuration

apps.toml controls the loadout. Each app owns its app_defaults.toml.
This app's apps_manager.updates section controls opt-in release URLs, trusted
public key, channel and owner notification intervals. Checks are disabled until
publishing is configured. Manual update commands reread those settings.

## Behavior

- Config/Reload are offered only for installed, enabled, loaded apps.
- Download alone changes neither program files nor loadout.
- New downloaded apps are installed disabled; existing loadout choices stay intact.
- Existing configuration is preserved, including during Force Replace.
- Every app_defaults.toml is backed up before copying, including disabled/custom apps.
- Modified official files are backed up with diffs and kept unless forced.
- Obsolete unmodified official files are removed; unrelated custom files are kept.
- MasterAdmins receive a private notice to run //pyres after copying.
- No automatic restart, new Python environments or automatic library installation.
- Managed local removal uses apps/00removed.

Publication and validation instructions: pyxaseco/management/UPDATER.md.

## Credits

Nila / PyXaseco project.
