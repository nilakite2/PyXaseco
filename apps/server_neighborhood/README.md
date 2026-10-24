# Server Neighborhood

## Purpose

Shows linked local servers, map information, player/spectator counts and native
join/spectate links.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/servers` | Open the server browser. | Everyone |

The Servers widget opens the same view. `/server` is the separate Server Info command.

## Configuration

Enable `app/server_neighborhood` and restart. Set `directory` in
`app_defaults.toml` to the same absolute local folder on all linked instances,
for example `'C:\TrackMania_Servers\Neighborhood'`.
Controller accounts need read/write access there, and each server needs a unique login.

The relative default is private to each controller and will not discover sibling
installations. `server_logins` optionally restricts the group. Supported settings
are editable through `//apps config server_neighborhood`.

## Changes And Limits

- Publishes local XML snapshots every ten seconds by default, without polling
  other dedicated servers. No database is required.
- Includes the current server marked `(here)`. The widget defaults to three rows;
  `entries` accepts 1-10 and `width` accepts 15.5-40.
- Stale/offline entries cannot be joined; full servers offer Spectate only.
  TMF still enforces capacity/password restrictions.
- F7, Classic/Modern styles and per-player accents apply.
- Shared snapshots contain server/map metadata and counts, not player rosters,
  passwords, database credentials or XML-RPC endpoints.
- Uses local folders, not FTP/HTTP relays or UNC transport. Moving an installation
  requires retiring its old snapshot before reusing the same login.

## Credits

Original Server Neighborhood: undef.de; contributors Milenco and .anDy.
PyXaseco adaptation: Nila / PyXaseco project.
