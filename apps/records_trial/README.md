# Trial Records

## Purpose

Integrates the Trial API: identifies Trial-enabled maps, fetches their records/run
information, sends server heartbeats and submits positive non-Stunts finishes.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/trialrecs` | Open the current map's Trial records. | Everyone |
| `/trialinfo` | Show map details, checkpoint tables, charts and map-page links. | Everyone |
| `/trialpb` | Show your saved Trial PB/rank and its checkpoint tables and charts, where available. | Everyone |

Recognised maps can also use the shared external-records HUD slot.

`/trialinfo` fetches fresh map details in the background: name, author,
environment, points, record count/best time, TMX information, dates, list and
UIDs, where supplied by the API. Longer information is paginated using the
player's selected UI style. Internal database/source configuration is not shown.

The `Trial page` entry opens the official `tmrpgtrial.com/map/<id>` page. The
separate `TMTG` entry opens `tmtrialgy.com` with the label `Open map on TMTG`.
Official links use saved map identities returned by
`/api/trial-tracks/<uid>?include_links=1`, requiring the updated website Trial
route. If no official map identity is available, `Trial page` shows `Not available`.
Browser links use HTTP for TMF compatibility.

Additional pages show website checkpoint statistics: average and median segment
times, average cumulative times, average respawns and sample counts. Native
ManiaLink bar charts display up to 24 checkpoint entries per page, with the same
scale across each chart's pages. Bars use half-width styling and every checkpoint
is labelled. The tables retain the exact times. Checkpoint
numbering matches the website; these are collected statistics, not personal or
live checkpoint splits. Missing samples are shown as `--`, not zero.

Checkpoint data comes from `/api/trial-checkpoint-stats/<uid>`. Missing data or
an unavailable checkpoint endpoint does not prevent the map details from opening.
No chart images or extra libraries are required.

`/trialpb` uses your game login to look up your record through the public API,
including linked-login bests returned by the API. It shows your PB even if no
checkpoint data exists. Checkpoint charts/tables use one complete saved run
whose finish time matches that PB; different replays/sources are not combined.
The checkpoint-run lookup returns at most 5,000 rows; missing, ambiguous or
incomplete PB runs are not charted. These are stored website records, not live
splits or a replacement for zTrack. No website sign-in is needed.

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
