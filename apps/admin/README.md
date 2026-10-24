# Admin

## Purpose

Administers the dedicated server, maps, players, permissions and controller.
Commands use `/admin <command>` or the shorter `//<command>` form.

## Commands

| Command | Purpose |
| --- | --- |
| `//help`, `//helpall` | List available administrative commands and syntax. |
| `//skip`, `//restart`, `//endround` | Control the current race/map. |
| `//add <TMX_ID>`, `//addlocal` | Add maps permanently; see command help for local-file syntax. |
| `//remove`, `//erase` | Remove a playlist entry; erase also removes its map file. |
| `//readtracklist`, `//writetracklist`, `/ms` | Load/save MatchSettings or open the MatchSettings picker. |
| `//forceteam <login> red\|blue`, `//forcespec` | Move a player to a team or spectators. |
| `//warn`, `//kick`, `//ban`, `//black` | Player moderation; corresponding removal/list commands are in help. |
| `//setgamemode`, `//setservername`, `//setpwd` | Change dedicated-server settings. |
| `//apps`, `//uistyle default <id>` | Manage apps or the default UI preset. |
| `//cleanupserver [db\|ms\|all]` | Review a server reset; destructive actions require confirmation. |
| `//shutdown`, `//shutdownall` | Stop PyXaseco, or PyXaseco and its dedicated server. |

`/st help` explains Stalker's Tools; `/chatall [page]` displays full chat history.
Access is ability-based through admin/operator settings; not every command
is available to every administrator. App management and server cleanup require
MasterAdmin. Use `//unlock` first when administrative locking is configured.

## Configuration

Use `app_defaults.toml`, controller settings and `adminops.toml` for defaults,
abilities and assigned roles. MatchSettings operations use the configured filename,
not an assumed hard-coded path. The dedicated-server account must allow the RPCs.

## Changes And Limits

- `//add` saves the permanent playlist to MatchSettings; public `/add` is temporary.
- Removing/erasing a map does not automatically skip the current map.
- Cleanup previews and backs up before destructive work. MatchSettings cleanup
  keeps the currently running map; database cleanup affects the entire configured
  database, including other instances if shared. Read the confirmation carefully.
- Configuration reload is separate from restarting/reloading Python source.
- Match and Stalker's Tools functionality remains grouped here rather than
  requiring a separate legacy PHP plugin layout.

## Credits

XAseco admin commands: Xymph (updates).
Stalker's Tools: STALKER-SVK. MatchSettings: doe-eye, adapted for XAseco by L3cKy.
PyXaseco adaptation: Nila / PyXaseco project.
