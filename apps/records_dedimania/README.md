# Dedimania Records

## Purpose

Fetches world records from Dedimania and submits eligible results. Supplies a
leaderboard window and the Dedimania provider for the shared external-records HUD.

## Commands

| Command | Purpose |
| --- | --- |
| `/helpdedi`, `/dedihelp` | Explain the Dedimania system. |
| `/dedirecs [help\|pb\|new\|live\|first\|last\|next\|diff\|range]` | Browse records or related information. |
| `/dedipb`, `/dedinew`, `/dedilive` | Show your PB, new records or online players' records. |
| `/dedifirst`, `/dedilast`, `/dedinext` | Show leading, last or next-better records. |
| `/dedidiff`, `/dedirange` | Show record differences/range. |
| `/dedicps` | Select Dedimania checkpoint comparison. |
| `/dedistats` | Show track statistics. |
| `/dedicptms`, `/dedisectms` | Show record checkpoint/sector times. |

## Configuration

Optional `app/records_dedimania`; disable it through `//apps`/the loadout and restart
when the service is not wanted. Use `app_defaults.toml`, supported `//apps` fields
and shared Dedimania controller settings. Account credentials belong in `.env`
or the supported legacy configuration, not in public README examples.

## Changes And Limits

- Optional isolation allows the controller and RPG/Trial apps to run without this
  app's folder. Disabling Dedimania does not disable those independent providers.
- External work uses background delivery. A network error is not an empty record
  list or proof that a submission was acknowledged.
- Dedimania applies its own eligibility and ranking limits; this is not unlimited
  local PB storage and does not cover Stunts records.
- The shared HUD slot may instead display recognised Ultimania/RPG/Trial records;
  the Local Records widget remains separate.
- The legacy API can use unencrypted HTTP. Submissions disclose the relevant
  player/map/record data to Dedimania; enable with that understanding.

## Credits

XAseco Dedimania integration and commands: Xymph, based on FAST.
PyXaseco adaptation: Nila / PyXaseco project.
