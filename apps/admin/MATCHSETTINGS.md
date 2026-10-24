# MatchSettings Picker

- `/ms` or `/ms list`: MasterAdmin-only, paged selection of local
  `GameData/Tracks/MatchSettings/*.txt` files. Uses the player's Classic/Modern style.
- Click a filename to load its playlist **and game settings**. This does not
  explicitly skip/restart the current map or stop the dedicated server.
- MasterAdmin status and the configured admin lock are checked on commands,
  pagination and load clicks. Closing/replacing the window invalidates its actions.
- `autosave.txt`, symbolic links and subdirectories are excluded. Selected files
  must be valid playlist XML (maximum 4 MiB).
- `Configured default` identifies the original controller setting; `Last loaded`
  identifies a load confirmed during this controller session. The dedicated
  server's startup playlist is not guessed from the controller setting.
- A confirmed load changes `settings.default_tracklist` **in memory**. Subsequent
  `//writetracklist`, permanent map additions and cleanup target that file.
  No configuration or dedicated launcher is rewritten. After a restart, the
  configured default and the launcher's MatchSettings argument still apply.
- `//readtracklist [filename]` uses the same confirmed loader, keeping existing
  admin permissions. Names without `.txt` get that extension; paths are refused.
  This command also works with remote dedicated servers, whereas listing local
  files through `/ms` requires a local absolute track directory.

Included in the existing Admin app; no new app configuration or database table.
Based on the Matchsettings plugin by doe-eye and L3cKy, supplied in `ToPort/`.
