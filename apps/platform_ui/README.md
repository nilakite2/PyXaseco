# Platform UI

## Purpose

Owns shared window styles, HUD panels, personal UI preferences and the 1.4
Classic/Modern preset system used by other apps.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/style list` | Choose a legacy window style. | Everyone |
| `/style <name>` | Select a named legacy style. | Everyone |
| `/style default`, `/style off` | Restore the legacy default or disable legacy window decoration. | Everyone |
| `/uistyle list` | Open the UI preset picker. | Everyone |
| `/uistyle <id>` | Save a preset without opening the picker. | Everyone |
| `/uistyle default` | Inherit the server default. | Everyone |
| `/recpanel`, `/donpanel`, `/votepanel` | Choose/configure records, donation and vote panels; use their help for options. | Everyone |
| `/settings [login]` | View personal settings; viewing another login requires the relevant ability. | Ability checked |
| `/lastwin` | Reopen the previous supported window. | Everyone |
| `//uistyle default <id>` | Save the server-wide inherited UI default. | Administrative ability |

The records-panel command is `/recpanel`, not `/recspanel`; `/recpanel off` hides it.

## Configuration

Use `app_defaults.toml`, `styles.toml`, `panels.toml` and the `uistyles/` catalogue.
See [Custom UI presets](uistyles/custom/README.md) for template instructions.
Preset 0 is Classic, 1 is Modern-Default; shipped accent variants/custom presets
use further IDs. Do not reuse an existing ID for an unrelated preset.

## Changes And Limits

- `/style` changes legacy window styling; `/uistyle` chooses the broader UI preset.
- Nullable `players_extra.ui_style` is added automatically when missing. A null
  preference follows the server default without overwriting other player settings.
- Preferences persist with the local database. Different players can use different
  presets simultaneously, including Classic and Modern.
- Shared presentation keeps icons, accents and controls consistent, but cannot
  freely remove every native TMF HUD element. No client texture-replacement mod
  is required or silently applied.

## Credits

XAseco styles, panels and Last Window: Xymph.
PyXaseco adaptation and UI presets: Nila / PyXaseco project.
