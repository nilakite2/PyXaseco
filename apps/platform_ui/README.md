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
| `/hud` | Preview personal visibility, position, size and legacy panel template changes. | Everyone |
| `/hud reset` | Remove personal HUD overrides for the current style. | Everyone |
| `/hud export` | Get a private 20-digit code for the active preset's saved HUD layout. | Configured servers |
| `/hud restore <code>` | Replace the active preset's HUD layout from a code. `/hud import` is an alias. | Configured servers |
| `/recpanel`, `/donpanel`, `/votepanel` | Choose/configure records, donation and vote panels; use their help for options. | Everyone |
| `/settings [login]` | View personal settings; viewing another login requires the relevant ability. | Ability checked |
| `/lastwin` | Reopen the previous supported window. | Everyone |
| `//uistyle default <id>` | Save the server-wide inherited UI default. | Administrative ability |

The records-panel command is `/recpanel`, not `/recspanel`; `/recpanel off` hides it.
`/recpanel inline` puts PB, Local, Dedi and TMX in one clickable row.

## Configuration

Use `app_defaults.toml`, `styles.toml`, `panels.toml` and the `uistyles/` catalogue.
See [Custom UI presets](uistyles/custom/README.md) for template instructions.
Preset 0 is Classic, 1 is Modern-Default; shipped accent variants/custom presets
use further IDs. Do not reuse an existing ID for an unrelated preset.

## Personal HUD Layout

Open `/hud` during a race. Select a panel, use Hide/Show, move it with the
direction buttons or change its size, then choose Save. Pick a movement step
of 0.1, 1 or 10; 1 is the default. Cancel discards the preview. Reset panel
restores that panel in the preview; `/hud reset` removes
all saved overrides for the active style, without touching other styles.

**Standard**, **Compact**, and **Minimal** are HUD layouts, independent of the
Classic, Modern, and FAST styles. Compact shrinks race panels (including
ManiaKarma, Discord, Force Play, Best Finishes, Best CPs, and CP Live). It
keeps the upper-left tiles spaced as a grid, tightens the right-hand records
stack below the native Prev/Best display, and nudges other side panels toward
their screen edge. Minimal
leaves the Menu, current map, and race checkpoint tools. The layout is shared
across styles, while individual panel overrides are still saved per style.
An explicit panel override wins over the selected layout. `/hud reset` also
returns the layout to Standard. If you hide the Menu button yourself, use
`/menu` to reopen it on servers that run Eyepiece.

Server owners can tune `scale`, `edge_shift`, `tile_spacing`, and `rail_spacing`
under `[platform_ui.hud.compact]` in `apps/platform_ui/app_defaults.toml`.
Restart the controller to apply changes. Spacing cannot contract below the
base Compact scale, and the upper-left grid retains a minimum gap. Compact
uses the tuned anchors in `hud_layout.py` when a widget is still at its stock
position. Already-tuned or independently configured positions are not
substituted. Per-player offsets apply after Compact placement. Standard and
Minimal keep the app's configured positions. Native TrackMania HUD elements
are not repositioned.

The editor covers the main race widgets, including the track, record lists,
checkpoint displays, clock and bar widgets, as well as PyXaseco's records,
admin, vote, donate and stats panels and the FAST race widgets. Eligible legacy
panels appear even if not currently drawn; the other panels must have been
emitted for the player. Layouts with unsupported geometry can
be hidden but not moved or resized. Native TMF UI, pop-up windows, score-only
widgets and unregistered optional widgets are not edited. The server's
configuration, permissions and existing F7 behavior still apply.

Select a legacy Admin, Records, Donation or Vote panel to cycle through its
templates or choose **Use default**. **Reset layout** changes only the personal
geometry and visibility, not the selected template. Templates share the same
saved choice as the legacy commands across styles; position, size and visibility
still belong to the current style. Vote previews cannot cast votes, and saved
layout changes apply the next time the real vote panel is displayed.

MasterAdmins can change the server-wide position of the Admin, Records,
Donation, Vote and Stats panels in `//apps config platform_ui`. These offsets
start at zero and move each selected template without replacing it or changing
any player's personal offset. Changes refresh active race panels without a
restart; transient panels such as Vote and scoreboard Stats use the new
position the next time they are drawn.

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
defaults are used. Files are written only on Save, `/hud reset`, or `/hud restore`; the final
reset removes an empty profile. This directory is server data, not part of
installer or updater packages.

## Portable HUD Layouts

1. Save your layout in `/hud`, then run `/hud export` or choose **Export saved**.
2. Connect to another participating server with the same TrackMania login.
3. Select the destination UI preset and run `/hud restore <code>` within 15 minutes.

Transfers include the saved panel offsets, sizes, visibility and shared HUD
density. They do not change the selected UI preset, other presets' saved
overrides, legacy template choices, server settings, or permissions.
Servers may use different default HUD placements, so the same offsets can
land differently. Unsaved editor changes are not exported.

Server owners opt in with `PYXASECO_HUD_TRANSFER_KEY` in `.env`. The key must
match the relay and should only be given to trusted server operators. With no
key, normal `/hud` editing is unchanged. The default relay is tmtrialgy.com.
Set `PYXASECO_HUD_TRANSFER_URL` only to use a different HTTPS relay base
(without `/export` or `/restore`).

## Records And Splits

Select a player in `/recs`, `/dedirecs`, `/trialrecs`, `/rpgrecs`, or
`/wrrecs` to see that record's available actions. **My PB** looks up an
unlisted Local or Trial PB when it is not in the leaderboard. In a split
window, `/recordcp <number>` jumps to the page containing that split.
**Compare against this run** uses zTrack and appears only for complete,
compatible split data. Use `/ztrack off` to stop the comparison.

Shared windows and personal UI preferences do not load Eyepiece. Eyepiece
owns its own race widgets and their placement, exposed to providers through
`apps.ui.record_widgets`.

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
