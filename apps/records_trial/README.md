# Trial Records

## Purpose

Integrates the Trial API: identifies Trial-enabled maps, fetches their records/run
information, sends server heartbeats and submits positive non-Stunts finishes.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/trialrecs` | Open the current map's Trial records. | Everyone |

Recognised maps can also use the shared external-records HUD slot.

## Configuration

Optional `app/records_trial`, depending on Platform Core and UI, not Dedimania.
No `app_defaults.toml` currently exists. Configure the `TRIAL_API_BASE` and
`TRIAL_API_TOKEN` constants in `service.py`; this app explicitly does not read
them from `.env`. The default base is `https://tmtrialgy.com`.

## Changes And Limits

- Reads `/api/trial-tracks/<uid>`, `/api/trial-records/<uid>` and the run endpoint.
  Writes use `/api/trial-servers/` and `/api/trial-finish`.
- Finishes are retained for delivery, validated against an API-recognised map,
  and applied only after a matching acknowledged response. The API decides whether
  a result changes the leaderboard.
- Unlike RPG Records, this app submits finish data rather than best-ghost replay
  files. No direct Trial MySQL access or local schema import is needed.
- Sends map UID, player login/nickname, time and server metadata to the API.
  An unavailable API is not evidence that a map has no records.
- This implements the existing Trial API contract; it is not automatically
  compatible with an unrelated website's new API.

## Credits

Nila / PyXaseco project; TM Trial Graveyard API integration.
