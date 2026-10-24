# Best Finishes

## Purpose

Displays the best finish results observed on the current map in a compact HUD
widget. It complements, rather than replaces, the saved Local Records leaderboard.
Derived from Best Runs, simplified to a vertical stack showing finish times
without the checkpoint breakdown.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/bestfinishes` | Reload this app's configuration. | Admin / MasterAdmin |

The command is a configuration reload, not a public widget-toggle command.

## Configuration

Optional `app/bestfinishes`. `app_defaults.toml` controls position, scale and the
number of finishes shown; supported fields are available through `//apps`.

## Changes And Limits

Uses native ManiaLink graphics and the shared Classic/Modern presentation path.
The displayed finish collection is current-map runtime data, not a new persistent
database table or an external records service.

## Credits

Based on Best Runs by galaad.
PyXaseco adaptation and simplified finish-time layout: Nila / PyXaseco project.
