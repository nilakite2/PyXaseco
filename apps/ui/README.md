# UI: Records-Eyepiece, ManiaKarma And Menu

## Purpose

Draws the main HUD: map information, records/live rankings, bar widgets, windows,
ManiaKarma voting and the FuFi menu. Uses Platform UI's per-player presets.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/eyepiece` | Show Records-Eyepiece help. | Everyone |
| `/togglewidgets` | Toggle widget visibility; F7 also controls visibility. | Everyone |
| `/elist` | Browse maps through the UI list. | Everyone |
| `/estat <view>` | Open a supported extended ranking/statistics view. | Everyone |
| `/eyeset` | Administrative Records-Eyepiece settings. | Administrative checks apply |
| `/karma` | Show the current map's karma and your vote. | Everyone |
| `/karma help`, `/karma details` | Explain voting or show detailed statistics. | Everyone |
| `/+++`, `/++`, `/+`, `/-`, `/--`, `/---` | Vote from fantastic to waste. | Subject to configured voting rules |

Record-list commands such as `/recs`, `/dedirecs` and `/rpgrecs` belong to their
respective apps. `/uistyle` belongs to Platform UI, not this command surface.

## Configuration

`app_defaults.toml` controls native custom-UI visibility, widget positions/rows,
icons, text/background styles, menu entries, ManiaKarma behavior and API/images.
Use `//apps config ui` for supported fields; free-form layouts/text may need file
editing followed by a supported reload.

## Changes And Limits

- Classic remains available; Modern and accent presets apply per player through
  shared rendering rather than replacing everyone's configuration.
- Modern lists fit existing entries; windows and widgets follow the selected UI preset.
- The external-record slot selects recognised Ultimania (Stunts), RPG, Trial or
  Dedimania data. These optional folders are not all required for UI startup.
- ManiaKarma delivery distinguishes acknowledged votes from unavailable lookups.
  Its remote API is separate from local records and depends on external uptime.
- TMF native clickable links require HTTP.

## Credits

Records-Eyepiece: undef.de; contributors .anDy and Bueddl.
ManiaKarma: undef.de. FuFi Menu: FuFi.
PyXaseco adaptation and Modern presentation: Nila / PyXaseco project.
