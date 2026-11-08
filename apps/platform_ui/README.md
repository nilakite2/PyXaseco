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
| `/hud` | Preview personal visibility, position and size changes for the current style. | Everyone |
| `/hud reset` | Remove personal HUD overrides for the current style. | Everyone |
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

## Personal HUD Layout

Open `/hud` during a race. Select a panel, use Hide/Show, move it with the
direction buttons or change its size, then choose Save. Cancel discards the
preview. Reset panel restores that panel in the preview; `/hud reset` removes
all saved overrides for the active style, without touching other styles.

The editor covers the main race widgets, including the track, record lists,
checkpoint displays, clock and bar widgets, as well as PyXaseco's records,
admin, vote, donate and stats panels and the FAST race widgets. It lists only
supported panels emitted for the player. Layouts with unsupported geometry can
be hidden but not moved or resized. Native TMF UI, pop-up windows, score-only
widgets and unregistered optional widgets are not edited. The server's
configuration, permissions and existing F7 behavior still apply.

Show/Hide also covers Best Finishes, Best CPs, Best Runs, Best Sectors, Best CP
Times, CP Live, ManiaKarma, zTrack, sponsor banners, Server Neighborhood,
Curated GPS, the Alternate Scoretable button, server banners, quick-chat
buttons, and race-phase round-score, donation and winning-payout widgets.
These additions are visibility-only. Multi-layer widgets are handled as one
panel, including their buttons and status indicators. Only currently emitted
race HUDs are listed; hiding an app's HUD does not disable its background
work or change another player's display. Optional apps remain optional.

Overrides use offsets from the server position and a size multiplier. Unchanged
settings keep inheriting the defaults. Each player has one TOML file under
`apps/ui/player_huds/`, named by the SHA-256 of their game login, with separate
sections per style. Only that file is read in the background on connect; there
is no startup scan or database migration. Invalid files are preserved and
defaults are used. Files are written only on Save or `/hud reset`; the final
reset removes an empty profile. This directory is server data, not part of
installer or updater packages.

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
