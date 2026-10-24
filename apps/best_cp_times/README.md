# Best CP Times

## Purpose

Displays checkpoint bests observed on the current map, either across players or
for the viewer personally. An accompanying inlay compares checkpoint times.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/bcps all` | Show shared checkpoint bests. | Everyone |
| `/bcps my` | Show your personal checkpoint bests. | Everyone |
| `/bcps` | Show usage and the current mode. | Everyone |

## Configuration

Optional `app/best_cp_times`. Edit `app_defaults.toml` or supported fields through
`//apps config best_cp_times`. `[best_cp_times_v2.config]` includes `rows`, size,
text scaling, spectator display and custom-UI settings; position has its own table.

## Changes And Limits

- Personal checkpoint bests improve only when a better time is passed; a worse
  attempt does not replace them.
- Row count is configurable rather than fixed in Python.
- This is session/current-map checkpoint tracking, not permanent PB storage.
  It does not introduce a database history of personal checkpoint runs.
- Shared Classic/Modern delivery, per-player modes and widget visibility apply.

## Credits

Original Best Checkpoint Times: undef.de.
PyXaseco adaptation: Nila / PyXaseco project.
