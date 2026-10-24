# DBTools

## Purpose

Creates local compressed SQL backups of the controller's configured database.
Optional; disabled in the default loadout.

## Commands

All commands and window actions require MasterAdmin and an unlocked admin session
when administrative locking is configured.

| Command | Purpose |
| --- | --- |
| `/dbtools backup` | Start a database backup. |
| `/dbtools listbackups` or `/dbtools list` | Browse backups, dates, sizes and status. |
| `/dbtools deletebackup <id>` | Review deletion of a local backup folder. |
| `/dbtools status` | Show the last operation and scheduling status. |
| `/dbtools help` | Show usage. |

Backup deletion requires the generated one-use confirmation within 120 seconds.

## Configuration

Enable `app/dbtools` and restart. Use `app_defaults.toml` or
`//apps config dbtools` for compression, limits, output, retention and scheduling.
Scheduling is off by default; `schedule.enabled` and `interval_hours` enable it.

Output defaults to `backups/dbtools/<timestamp>-<id>/`, with SQL/gzip data and
a manifest/checksum. Copy backups elsewhere for protection against disk failure.
They contain sensitive database data: keep them outside public/web directories.

## Changes And Limits

- Backs up all base tables in the configured database, including other instances'
  data when the database is shared. Player accounts/grants, routines, events and
  MariaDB server settings are not included.
- InnoDB tables use a consistent transaction snapshot. MyISAM/Aria tables are
  live, best-effort exports and may reflect different moments during concurrent
  writes. The backup browser marks this mode `live*`.
- No explicit table locks, temporary database or controller restart is used.
  Avoid schema changes during backup; unsupported engines, views and custom
  triggers are rejected.
- SQL import replaces target tables. Select the target database before importing
  and stop all controllers/external writers using it. There is no in-game restore.
- Only completed backups receive a checksum and successful status. Failed or
  interrupted output is not a usable backup and does not trigger retention cleanup.
- Retention removes old completed backups while preserving `keep_last` and the
  latest backup. `retention_days = 0` disables pruning.
- One operation runs at a time, with configured size limits and a five-minute
  deadline. Use external database tools for larger/slower exports.
- A server-folder ZIP is separate from a SQL backup. FTP, database wiping,
  optimization, repair and automatic record pruning are not provided.

## Credits

Original DBTools: vni (jimpower), with a sector-records fix by amgreborn.
PyXaseco backup implementation: Nila / PyXaseco project.
