# Custom UI Presets

Copy `../Template.toml.example` here as `<name>.toml`, with a unique integer ID
from 2 to 2147483647. IDs 0 and 1 are reserved. Files are read at controller startup;
renaming a file or changing its display name does not change its identity.

Duplicate IDs are rejected, not reassigned. Invalid files are skipped with a warning.
The starter example outside this folder has no reserved ID and is not loaded.

## Supplied Modern Colors

| ID | Name |
| --- | --- |
| 1 | Modern-Default (original cyan; stored in `../builtin/modern.toml`) |
| 2 | Modern-Purple |
| 3 | Modern-Red |
| 4 | Modern-Green |
| 5 | Modern-Orange |
| 6 | Modern-Blue |
| 7 | Modern-Pink |

The color variants override `accent`, `selection` and `header`. Headers use the
selection hue with the original Modern header transparency, so records, track
information, ManiaKarma and command windows match the chosen color as well.
All other colors,
transparency, sizing and behavior inherit Modern-Default. Existing ID 1 preferences
remain valid. Use an unused ID (8 onward in this distribution) for a new preset;
do not renumber existing presets, since player preferences store the numeric ID.
Restart the controller after adding or editing files, then use `/uistyle list`
or `/uistyle <id>`. No database migration is needed for additional presets.

## Customization

Classic-based presets (`base = 0`) can optionally select an existing window
style using `window_style`. This overrides window presentation only while that UI
preset is active; it does not overwrite the player's `/style` preference.

Modern (`base = 1`) covers the shared HUD, race/score widgets, menus, panels and
command windows, including UI from enabled optional apps. Existing artwork,
team/status colours, inputs, links and actions are preserved. Bespoke windows keep
their existing layouts, with Modern backdrops; shared command tables use the
native Modern renderer. An explicit `window_style` overrides shared command-window
presentation in a custom preset; otherwise Modern controls these windows.
Copy any colors from `../builtin/modern.toml` into a `[palette]` table to override
them. Only listed keys and 3/4-digit hexadecimal TMF colors are accepted.
Positions, width, row spacing and the record-count limit stay in the existing UI
configuration. Modern fits its height to actual records (no unused slots or
synthetic no-record row), rather than reserving the configured fixed height.
Modern command windows also fit short pages. No external assets are required.
Classic and `/style` preferences remain stored and are restored with `/uistyle 0`.
Only enabled apps participate; UI styling never enables an app or changes its data.

Keep these custom files when upgrading. Use `/uistyle list` to select a loaded preset,
`/uistyle default` to inherit the server default, and `//uistyle default <id>` to
change the server default with the appropriate admin rights.
