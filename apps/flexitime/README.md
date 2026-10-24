# FlexiTime

## Purpose

Provides flexible Time Attack limits with a remaining-time HUD, pause/resume,
manual adjustments and optional saved per-map limits.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/timeleft` | Show remaining time. | Everyone |
| `/timeleft <minutes>` | Set remaining time. | Configured time managers |
| `/timeleft +<minutes>` or `-<minutes>` | Add/remove remaining minutes. | Configured time managers |
| `/timeleft pause\|resume` | Pause/resume the timer. | Configured time managers |
| `/tl` | Alias of `/timeleft`. | Same checks |
| `/timeset <minutes>` | Save a custom limit for the current map. | Configured time managers |

## Configuration

Optional `app/flexitime`. `app_defaults.toml` controls access level/whitelist,
default minutes, author-time multiplier, minimum limit, custom limits and HUD
colors/warning thresholds. Per-map custom times require the local database.
Supported defaults are editable through `//apps config flexitime`.

## Changes And Limits

Uses app-native TOML and the shared local database service instead of legacy
plugin imports. Active in Time Attack only. Time adjustments affect the running
timer; `/timeset` is the separate persistent per-map setting. Runtime timer state
is not a permanent paused-session snapshot.

## Credits

Original FlexiTime: Tony Houghton (realh).
PyXaseco adaptation: Nila / PyXaseco project.
