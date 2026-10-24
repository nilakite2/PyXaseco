# Players

## Purpose

Provides player listings, statistics, visits, clans, wins and the local server's
record-based player ranking.

## Commands

| Command | Purpose |
| --- | --- |
| `/players`, `/ranks`, `/clans` | List connected players, their ranks or clans. |
| `/stats`, `/statsall` | Show player statistics and expanded statistics. |
| `/wins`, `/laston` | Show wins or last-seen information. |
| `/rank`, `/nextrank` | Show your rank and progress toward the next rank. |
| `/top10`, `/top100` | List leading ranked players. |
| `/topwins`, `/topclans`, `/topdons` | List leading winners, clans or donors. |
| `/active` | Show activity standings. |

These are player-facing views; supported target/filter syntax is shown by each
command's help. `/pb` belongs to Local Records, not this app.

## Configuration

Use `app_defaults.toml` for ranking thresholds/limits and supported `//apps`
settings. Uses Platform Core's local database and existing player/record data.

## Changes And Limits

- Ranking work runs in the background, keeping the last complete ranking usable
  while recalculation is in progress.
- Ranking limits such as `maxrecs` restrict ranking calculations, not the storage
  of every player's personal best. Local Records has separate leaderboard limits.
- Local server rank is not Nadeo ladder rank, Dedimania rank or a global website
  ranking. Results depend on local data and configured minimum-map requirements.

## Credits

XAseco player commands: Xymph. RASP: Xymph and AssemblerManiac.
PyXaseco adaptation: Nila / PyXaseco project.
