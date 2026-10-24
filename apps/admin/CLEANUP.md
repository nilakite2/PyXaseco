# Event Server Cleanup (MasterAdmin Only)

`//cleanupserver` shows information and never changes anything.

| Command | Scope |
| --- | --- |
| `//cleanupserver db` | Empty every base table in the controller's configured database and reset table counters. Preserve table definitions, views, routines, database and database user. |
| `//cleanupserver ms` | Keep exactly one entry for the running map in the configured MatchSettings file and reset `startindex` to 0. Preserve game settings. |
| `//cleanupserver all` | Both scopes above, not a filesystem/factory reset. |

Each scoped command is a **preview**. It shows the actual database/table count
and/or MatchSettings path, and a confirmation command with a one-use code valid
for 120 seconds. Confirmation belongs to that MasterAdmin's current connection.
Players and spectators can remain connected. Admins and Operators cannot use
cleanup even if their ability lists are edited to include it.

## What Happens After Confirmation

1. The dedicated server always stays running. For `db`/`all` only, briefly stop
   controller processing, run shutdown hooks, stop background workers and apps,
   and close the normal database pool. `ms` runs without stopping either process.
2. Back up selected database tables (definitions and data) and/or MatchSettings
   under `<controller>/.server-cleanup/<timestamp>/`. Backups contain sensitive data.
3. For `ms`/`all`, read the running map UID/filename from the dedicated server.
   Keep exactly one entry for it, creating the entry if it was not saved before.
4. Atomically update MatchSettings and/or truncate all selected database tables.
   After successful `db`/`all`, restart only PyXaseco to discard old cached IDs.
5. Log completion or failure and save `result.json` beside the backups.

No `QuitServer`, service stop, race restart or map change is requested. MatchSettings
cleanup changes the saved file, not the dedicated server's current in-memory rotation.
Reload the saved MatchSettings when you want to apply its one-map rotation live.
New rows for connected players/maps are created normally after the controller restart.
Finishes during the brief controller restart are not recorded.

## Important Boundaries

- This empties the **whole configured database**, not just known core tables.
  Local records, players, personal UI preferences, karma caches, rankings and
  optional-app data such as curated GPS and FlexiTime are lost. Never use it when
  another controller/application shares that database. System databases are refused.
- All backups must finish before the first destructive change. Permission errors,
  stale targets, invalid XML, missing local paths or backup failures abort cleanup.
- Databases with custom triggers are refused; use external database tools instead.
  Backups contain table definitions/data, not server accounts or database routines.
- SQL truncation is not transactional. `all` is not atomic across files and SQL.
  A later failure may leave a partially reset server; review `result.json` and use
  the backups before starting again. On failure, no automatic controller restart,
  rollback or retry is attempted. Disable external unconditional watchdogs if they
  would restart a controller after a failed maintenance operation.
- Map files, dedicated configuration, credentials, admin lists, apps, quotes,
  sequential messages, other MatchSettings files, logs and controller state files
  are not removed. Remote Dedimania/RPG/Trial/ManiaKarma data is not deleted.
- MatchSettings comes from `settings.default_tracklist` (normally
  `MatchSettings.txt`) within the dedicated server's local `trackdir/MatchSettings/`.
  A remote/nonlocal dedicated-server filesystem is not supported by this command.

To restore a SQL backup, keep controllers stopped, select the intended database
and import `database.sql` with a database administration tool. Restore the saved
MatchSettings file to its reviewed location if needed. Backups replace table
contents; inspect them before importing into any database.
