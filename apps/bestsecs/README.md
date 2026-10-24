# Best Secs

## Purpose

Tracks sector times: elapsed time between consecutive checkpoints. Stores overall
sector records and each player's own best sectors in the controller database.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/secrecs` | Show overall sector records. | Everyone |
| `/mysecrecs` | Show your own sector records. | Everyone |
| `/delsecs` | Delete all sector records for this map. | Operator / Admin / MasterAdmin |
| `/delsec <N>` or `/delsec <N-M>` | Delete one sector or a range. | Operator / Admin / MasterAdmin |
| `/secrecs_cleanupdb` | Clean orphaned/duplicate sector records. | MasterAdmin |

Administrative deletion still requires the handler's permission checks; it is
not available to ordinary players. Back up the database before maintenance.

## Configuration

Optional `app/bestsecs`. `app_defaults.toml` controls announcements, comparison
behavior, deletion policy, position and game-mode visibility. Supported fields
are editable through `//apps`. Requires the local database service.

## Changes And Limits

Uses `secrecs_all` and `secrecs_own` for persistent overall/personal sector bests.
This differs from session-only Best CP Times: sectors are split durations, not
cumulative checkpoint times. Shared PyXaseco UI delivery replaces the PHP widget.

## Credits

Original Sector Records / BestSecs: DarkKnight and amgreborn.
PyXaseco adaptation: Nila / PyXaseco project.
