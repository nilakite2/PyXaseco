# Mania Records (WRMania)

## Purpose

Optional global timed records using WRMania's v1 API. Validated improvements are
submitted independently of which records widget is visible. No replay upload is
required by this protocol: runs contain times and checkpoint splits.

The shared widget keeps Ultimania, RPG and Trial priority. Mania Records appears
only when Dedimania is disabled/unavailable for the current map. An empty but
healthy Dedimania leaderboard is still available. Classic/Modern styles, F7,
positions and row counts follow the existing external-record widget settings.

## Configuration

1. Enable `app/records_wrmania` in `apps.toml`, or through `//apps`, then restart.
2. Configure `apps/records_wrmania/app_defaults.toml`: actual dedicated-server
   login, password and three-letter nation. These are NOT XML-RPC credentials.
   Blank login uses the connected server's login; mismatched logins are rejected.
3. Prefer `WRMANIA_SERVER_PASSWORD` in the controller's `.env` for the password.
   It overrides `server_password` in the app defaults. The plain password is not
   sent: authentication sends the supplied plugin's password-derived HMAC proof
   over verified HTTPS, and subsequent requests use an in-memory session token.

`//apps config records_wrmania` edits supported defaults.
`//apps reload records_wrmania` reloads configuration; use `//pyres` after source edits.

| Setting | Default | Purpose |
| --- | --- | --- |
| `submit_records` | true | Continue submissions regardless of widget visibility. |
| `widget_enabled` | true | Allow the shared Mania Records widget. |
| `prefer_widget` | false | Prefer Mania over Dedimania, but never RPG/Trial/Ultimania. |
| `show_record_messages` | true | Announce verified improvements when chat priority permits. |
| `show_map_messages` | true | Announce one map summary when chat priority permits. |
| `announce_when_hidden` | false | Override chat priority, without changing widget priority. |
| `refresh_interval` | 45 | Seconds between background refreshes. |
| `heartbeat_interval` | 240 | Independent server-presence interval, 30-240 seconds. |

Presence updates continue on unsupported maps, with the widget hidden and with
record submissions disabled. Each heartbeat reads `GetServerName` and sends it
as `serverName`; the cached dedicated name is used if that query fails. Failed
heartbeats retry within 60 seconds. Records refreshes do not postpone heartbeats.

Chat and widget priority are separate:

- Healthy Dedimania: submit silently, without automatic Mania announcements.
- Dedimania loaded but unavailable: show and announce Mania only when RPG, Trial
  and Ultimania do not own the shared widget.
- Dedimania disabled/not installed: announce Mania even when RPG/Trial owns the
  widget. RPG/Trial widget priority is unchanged.

Keep both message settings false for fully silent operation. Existing settings
are preserved during updates; enable these explicitly if your saved values are false.
Explicit player commands still reply privately. Announcements use the external-record claimed/gained/
secured format and existing server colours, not Local Records formatting.

## Commands

| Command | Purpose |
| --- | --- |
| `/wr`, `/wr recs`, `/wrrecs` | Open the current leaderboard. |
| `/wr pb` | Show your best visible Mania Record. |
| `/wr next` | Show the next better place and gap. |
| `/wr diff` | Show the gap to first place. |
| `/wr help`, `/wrhelp` | Command help. |

## Limits

- Time Attack/Laps use the `ta` leaderboard; Rounds/Team/Cup use `rounds`.
  Stunts and forced-lap rounds are excluded, as in the source adapter.
- Author time must be at least 8 seconds; run time at least 6 seconds. Full,
  strictly increasing checkpoint splits ending at the finish are required.
- Displayed records respect the API's authenticated 30-40 place entitlement;
  widget settings cannot unlock additional places.
- Submissions use the controller's existing retained-record queue. Its configured
  memory/durable storage policy applies; this app creates no separate database.
  Temporary/uncertain sends retry with the same captured `eventId`, as in the
  source adapter, so duplicate acknowledgements do not announce a second record.
  Definitively rejected runs remain retained as failed for inspection.
- No PHP updater, installer, Dedimania disabling or legacy widget renderer is ported.
  Its live-feed command extension is not included. Checkpoint/sector comparison
  and split listings belong to optional zTrack; see `../ztrack/README.md`.
- zTrack reads complete cached Mania splits through the registered service.
  Mania Records does not require zTrack, and zTrack does not require Mania Records.

## Credits

Protocol: supplied WRMania / Mania Records XASECO adapter 0.19.0.
Its credits name undef for Records Eyepiece, Slig for the record-sharing idea,
and TM-Hub for API-design inspiration. Python integration: Nila / PyXaseco project.
The supplied GPL-3.0 notice is retained as `COPYING-GPL-3.0.txt`.
