# Best Runs

## Purpose

Displays leading run results with checkpoint information for the current map.
Useful for seeing how runs developed rather than only their final finish time.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/bestruns` | Reload this app's configuration. | Admin / MasterAdmin |

## Configuration

Optional `app/bestruns`. `app_defaults.toml` controls position, scale, total rows,
how many runs include checkpoints and the maximum displayed checkpoint count.
Supported settings are also available through `//apps config bestruns`.

## Changes And Limits

Shared Classic/Modern rendering replaces an isolated legacy widget layout.
Run collections are runtime/current-map data. This app does not replace Local
Records, persist a complete run history or submit records externally.

## Credits

Original Best Runs: galaad.
PyXaseco adaptation: Nila / PyXaseco project.
