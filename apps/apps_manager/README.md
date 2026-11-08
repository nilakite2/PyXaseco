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
| `//apps updates` | Check that GitHub and the website approve the same release catalogue. |
| `//apps download <package>` | Download and verify a controller or optional-app ZIP. |
| `//apps review <package>`, `//apps update <package>` | Review proposed file changes. |
| `//apps update <package> confirm` | Back up and copy, preserving modified code. |
| `//apps update <package> force confirm` | Also replace modified official code after backup. |

## Configuration

apps.toml controls the loadout. Each app owns its app_defaults.toml.
This app's apps_manager.updates section controls opt-in release URLs, verification
mode, channel and owner notification intervals. Checks are disabled until
publishing is configured. Manual update commands reread those settings.
SHA-256 mode validates matching catalogues and checksums from both publishers;
it does not require a signing key. Enable it only after both publishers are ready.
Full releases use one original `PyXaseco_v<version>.zip` for the controller and
all apps. Controller updates select only core files and already-installed
optional apps, including disabled ones. To install a missing app explicitly,
use its app ID with the download/update commands; only that app is copied
from the same ZIP and it is added to the disabled loadout.

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

## Credits

Nila / PyXaseco project.
