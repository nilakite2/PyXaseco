# PYXA Stats

## Purpose

Optional publisher for server snapshots and recent local records.
Separate from Server Info and the local ServerStats history app.

## Commands

No direct chat command. `/server` shows the enabled integration's health.

## Configuration

Enable `app/pyxa_stats` and restart. Set `PYXA_STATS_API_BASE` and
`PYXA_STATS_API_TOKEN` in `.env`. No destination/token is preconfigured.
Use `app_defaults.toml` or `//apps config pyxa_stats` for publishing,
heartbeat timing and the number of recent records.

Legacy `PUBLIC_STATS_API_BASE` / `PUBLIC_STATS_API_TOKEN` and supported
`config.toml` settings remain accepted. New names take precedence; an explicitly
empty new API base disables publishing.

## Changes And Limits

- Sends server/map metadata, version, player/spectator counts and recent local
  record events, including player logins/nicknames.
- Does not send IP addresses, complete rosters or server/database passwords.
- API routes remain `/api/public-stats/heartbeat` and
  `/api/public-stats/recent-record`.
- Disabling publishing pauses queued records; ambiguous submissions are not
  automatically resent.
- The app must be loaded to publish. Server Info alone does not send statistics.

## Credits

Nila / PyXaseco project.
