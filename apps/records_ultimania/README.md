# Ultimania Records

## Purpose

Displays and submits Stunts records through the Ultimania v5 API, including
optional best-ghost replay uploads. Requires a Stunts-capable dedicated server.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/ultirecs`, `/ultilist`, `/ultiwindow` | Open the current map's leaderboard. | Everyone |

The external-records widget opens the same window when Ultimania is selected.

## Configuration

Enable `app/records_ultimania` and restart. Use `app_defaults.toml` or
`//apps config records_ultimania` for API, refresh and submission settings.
The default endpoint is `http://ultimania5.askuri.de/api/v5/`.

Set `register_maps = false` and `submit_records = false` for read-only use.
Set `upload_replays = false` for score-only submissions.
Replay capture requires local dedicated-server access and write permission in
`Tracks/Replays/PyXasecoUltimania/`.

## Changes And Limits

- Recognised Stunts maps take priority in the shared RPG/Trial/Dedimania widget
  slot. Local Records remains separate.
- Widget position/rows use UI's Dedimania Stunts settings; score placement uses
  the shared external-record configuration. F7 and per-player styles apply.
- Scores are points, higher is better. Only positive improvements are submitted.
- Submission registers missing maps/players, saves the score, then uploads the
  replay against the acknowledged record ID. Failed capture permits score-only delivery.
- HTTP is unencrypted. Enabled submissions send map/player names, logins, scores
  and, when selected, replay data to the external service.
- Ambiguous score writes are not automatically resent. A failed replay upload
  retains its local file without resubmitting the acknowledged score.
- Replay limits are 64 MiB per upload and 1000 files/2 GiB retained locally.
  Successful uploads delete their own replay file.
- PHP self-updating and global-to-local record imports are not included.

## Credits

Original Ultimania client: askuri. Original plugin copyright: Martin Weber.
PyXaseco adaptation: Nila / PyXaseco project.
