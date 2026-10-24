# ForceMods

## Purpose

Applies server-wide environment mods, with optional per-map assignments.
Mods are selected for the next map load or restart, not individually per player.

## Commands

All commands require MasterAdmin and an unlocked admin session when configured.

| Command | Purpose |
| --- | --- |
| `/fmods`, `/fmods help` | Open settings or show usage. |
| `/fmods list` | List server maps and assigned mod/fallback policy. |
| `/fmods off` | Suspend server-forced mods without deleting assignments. |
| `/fmods sequential` or `random` | Choose environment rotation mode. |
| `/fmods override on\|off` | Replace/respect map-embedded mods during rotation. |
| `/fmods <environment>` | Open that environment's mod list. |
| `/fmods reload` | Reload saved settings. |
| `/fmods add [<id>] <url>` | Add a map assignment. |
| `/fmods mod [<id>] <url>` | Replace a map assignment. |
| `/fmods rem [<id>] [<url>]` | Remove an assignment. |
| `/fmods del [<id>] [<url>]` | Alias for `rem`. |

Without an ID, assignment commands target the current map. IDs come from
`/fmods list`. An optional removal URL must match the saved URL.

## Configuration

Enable `app/forcemods` and restart. Environment lists and permanent defaults
are in `app_defaults.toml`; supported fields are editable through `//apps`.
Mode/GUI toggles are runtime settings. Map assignments save immediately to
the automatically created `forcemods_tracks` table.

## Changes And Limits

- Assigned map mods take priority over environment rotation and embedded mods.
  Removing an assignment restores the normal fallback policy.
- `off` clears server forcing but does not block mods embedded in maps.
- URLs must be direct HTTP environment ZIPs. HTTPS input is normalized to HTTP;
  HTTPS-only downloads/redirects are not supported by TMF.
- Changes never automatically restart or skip a map. Already loaded client
  textures cannot be removed instantly.
- Failed next-map/database lookups clear stale queued forcing where possible.
- Disabling/shutdown restores the previous native settings only if another tool
  has not changed them. Use one forced-mod manager per dedicated server.
- The list shows assigned policy, not each client's download status.

## Credits

Original ForceMods: schmidi.
PyXaseco adaptation and per-map assignments: Nila / PyXaseco project.
