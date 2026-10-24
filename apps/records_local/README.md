# Local Records

## Purpose

Provides local record/PB commands and ranked record lists backed by the controller
database and shared record services. The UI app renders the corresponding HUD.

## Commands

| Command | Purpose |
| --- | --- |
| `/recs [help\|pb\|new\|live\|first\|last\|next\|diff\|range]` | Current-map records and related views. |
| `/pb` | Show your saved personal best on the current map. |
| `/newrecs`, `/liverecs` | Show new records or records belonging to online players. |
| `/firstrec`, `/lastrec`, `/nextrec` | Show the leader, last record or next record to beat. |
| `/diffrec`, `/recrange` | Show record differences/range. |
| `/best`, `/worst`, `/summary` | Show a player's record results/summary. |
| `/topsums`, `/toprecs` | Show aggregate record standings. |

## Configuration

No app-specific defaults file. `settings.toml`'s `[localdatabase].limit` controls
the loaded local leaderboard size; `apps/ui/app_defaults.toml` controls widget
rows/layout. Player-ranking `maxrecs` is a third, separate setting.

## Changes And Limits

- Personal-best storage is independent of the leaderboard limit: a player outside
  the top 50 can still have a saved PB. `/pb` can read it beyond the visible board.
- Time records improve downward; Stunts scores improve upward.
- Requires the local database, not Dedimania, RPG, Trial or another optional API.
  Database backups are needed to preserve saved records; copying map files alone
  does not back up PBs.

## Credits

XAseco record commands: Xymph. RASP: Xymph and AssemblerManiac.
PyXaseco adaptation: Nila / PyXaseco project.
