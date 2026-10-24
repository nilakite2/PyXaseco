# Match Overlay

## Purpose

Shows live Team-mode map points alongside a manually managed match/series score.
Uses native ManiaLink graphics and Classic/Modern styling.

## Commands

All commands require Admin or MasterAdmin.

| Command | Purpose |
| --- | --- |
| `/moverlay enable` or `activate` | Show the overlay in Team mode. |
| `/moverlay disable` | Hide the overlay. |
| `/moverlay status`, `help` or `about` | Show state or usage. |
| `/moverlay team 1 <name>`, `team 2 <name>` | Name Blue and Red; `blue`/`red` also work. |
| `/moverlay team auto <1\|2>` | Suggest a name from common text in team nicknames. |
| `/moverlay mscore <blue> <red>` | Set the overall match score. |
| `/moverlay to all\|players\|spectators` | Select the audience. |

## Configuration

Enable `app/match_overlay` and restart. `app_defaults.toml` and
`//apps config match_overlay` control position, width, names, audience,
autostart, refresh interval and score-screen visibility.
Defaults: manual activation, Team mode, spectators only, hidden on the score screen.

## Changes And Limits

- Map points update from the dedicated server; the overall match score is manual.
  No team assignments, game scores or map rotation are changed.
- Names/match score survive map changes within the controller session. Restarting
  the controller resets the match score; `mscore 0 0` resets it manually.
- Runtime commands do not save permanent defaults. Configuration reload reapplies
  defaults while preserving the manual match score.
- Leaving Team mode disables display until re-enabled. F7 and per-player styles apply.
- Automatic naming needs at least two team players; manual names remain available.

## Credits

Original Match Overlay: Chris92 and TheM; inspired by svenstucki's ESL TV tSplash.
PyXaseco adaptation: Nila / PyXaseco project.
