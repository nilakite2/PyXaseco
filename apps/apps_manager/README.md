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
| `//apps preview` | Open the Race HUD / Score Screen chooser for all six modes. |
| `//apps preview <race\|score\|table\|off> [mode]` | Preview a layout or stop it. The mode defaults to the server's current mode. |
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

- **Active now** reflects the running controller. **Pending restart** means
  saved changes have not been loaded. **Downloaded, not installed** means
  the approved ZIP is staged, not copied into the controller.
- Update Review starts with file counts, what will be preserved, and the next
  action. Review, confirmation, and restart stay separate.
- Config/Reload are offered only for installed, enabled, loaded apps.
- Layout fields use the same 0.1, 1 and 10 point steps in both directions.
  Positions use Left/Right and Up/Down; dimensions, row heights and scaling
  use plus/minus. Numeric strings (including 0 and 1) and paired Menu values
  stay numeric in the editor, and existing TOML keys and storage formats are
  preserved. A step outside a widget's permitted range is rejected before saving.
  Whole-number counts and SVG graph pixel sizes are not fractional layout fields.
- Use `//apps config platform_ui` for the server-wide legacy panel positions.
  Those position edits apply without a restart.
- `//apps config ui` opens seven submenus instead of one long list. **Back**
  returns from an item to its group, then from the group to UI Config.
- **Scoretable Lists** also contains the score-screen widgets and their
  positions, including the Eyepiece badge, Karma Reminder, and score bars.
  Clock and Favorites still share their on/off setting and size with the race HUD.
  **Your Stats** adjusts the same position as in Platform UI. Its visibility
  on the real scoreboard is controlled by `[server].sb_stats_panels` in `settings.toml`.
- **Layout Preview** shows the race HUD or score layout for Time Attack, Rounds,
  Team, Laps, Stunts or Cup without changing the live mode. For example,
  `//apps preview race team` shows a Team HUD on a Time Attack server.
  When editing UI from an active preview, the editor uses its selected mode.
  **Score Screen Preview** and `//apps scorepreview on/off/table` remain available.
  A preview temporarily hides the
  requesting MasterAdmin's race HUD. The preview uses sample data; widgets
  cannot be clicked, and **[Off]** widgets stay disabled on the real scoreboard.
  Settings still save normally and refresh the preview as you edit. **Stop**,
  the real score screen, and map changes close the preview.
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
