# Jukebox

## Purpose

Provides map browsing, player map requests, recent history, automatic jukeboxing
and TMX search/download requests.

## Commands

| Command | Purpose |
| --- | --- |
| `/list` | Browse server maps; `/list help` explains filters. |
| `/jukebox` (`/jb`) | Manage map requests; see its help for subcommands. |
| `/autojuke` (`/aj`) | Use automatic map requests where enabled. |
| `/add <TMX_ID> [section]` | Download/add a temporary map from TMX. |
| `/tmxr` | Request a random TMX map using the configured filters. |
| `/history` | Show recently played maps. |
| `/xlist` | Search TMX; `/xlist help` explains search syntax. |
| `/xlist tags` | Choose a TMX tag and browse matching maps. |
| `/y` | Vote yes for an active supported chat vote/request. |

Access, request limits and cooldowns depend on server settings. Permanent map
addition is Admin's `//add`, not the public `/add` command.

## Configuration

Use `app_defaults.toml`, supported `//apps config jukebox` fields and controller
settings for queue, voting and TMX policies. Uses shared map-list/TMX services.

## Changes And Limits

- Temporary `/add` does not permanently write the map to MatchSettings; `//add` does.
- TMX work runs through background jobs instead of blocking gameplay callbacks.
- The tag picker uses TMX metadata rather than requiring a hard-coded tag list.
- Dedicated-server map type, current mode and Nations/United compatibility still
  apply. Downloading a map does not guarantee `AddChallenge` will accept it.
- Endless TMX Random is a separate optional app, not mandatory jukebox behavior.

## Credits

RASP: Xymph and AssemblerManiac.
PyXaseco adaptation: Nila / PyXaseco project.
