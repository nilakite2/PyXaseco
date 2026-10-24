# RPG Records

## Purpose

Integrates the RPG records API at tmrpg.com. Displays recognised maps' records and
uploads replays for qualifying local-record results through the API's upload flow.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/rpgrecs` | Open the current map's RPG leaderboard. | Everyone |

The shared external-records widget opens the same records view when RPG is the
selected provider.

## Configuration

Optional `app/records_rpg`, depending on Platform Core and UI, not Dedimania.
This app currently has no `app_defaults.toml`: API base/token, endpoint paths and
replay settings are constants in `service.py` (`RPG_API_BASE`, `RPG_API_TOKEN`,
`RPG_SAVE_SUBDIR`, etc.). They are not automatically read from similarly named
environment variables. The default API base is `https://www.tmrpg.com`.

## Changes And Limits

- Lookups/submissions use background jobs and captured map identity, avoiding
  stale responses overwriting another map's records after a transition.
- Saves best-ghost replays through the dedicated server, then uses the API's
  presigned upload flow. Local dedicated replay-folder access is required.
- Successful uploads can delete their own local replay file; failed delivery is
  not treated as success. Replay storage has file-count/size bounds.
- Player logins/nicknames and replay/record data are sent to the external service.
  An API-compatible server and any required token are prerequisites.
- This is not a direct connection to the website's MySQL database or an import
  of all RPG records into Local Records.

## Credits

PyXaseco integration: Nila / PyXaseco project. Records/API: tmrpg.com / achepta.
