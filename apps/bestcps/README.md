# Best CPs

## Purpose

Shows a compact list of the best checkpoint times on the current map.
This is separate from the larger Best CP Times app and its `/bcps` modes.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/bestcps` | Toggle the widget for yourself. | Everyone |

## Configuration

Optional `app/bestcps`. Use `app_defaults.toml` for layout, row counts and display
settings, or `//apps config bestcps` for supported fields.

## Changes And Limits

Uses the shared PyXaseco widget delivery/style path instead of a standalone PHP
plugin. Data is tracked for the current map/session; this is not a replacement
for Local Records or a database-backed personal-best archive.

## Credits

Original Best Checkpoints: galaad. Real-time updates and hide/show controls: nerve6.
PyXaseco adaptation: Nila / PyXaseco project.
