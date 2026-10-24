# JFreu

## Purpose

Groups the JFreu server/community tools: rank-based admission, spectator handling,
messages, announcements and associated administrative controls.

## Commands

| Command | Purpose |
| --- | --- |
| `/jfreu help` | List the JFreu controls and their syntax/access rules. |
| `/ranklimit` | Show the active rank-limit policy. |
| `/password` | Privately show the relevant player/spectator join password. |
| `/unspec` | Request return from spectator status where permitted. |
| `/yes`, `/no` | Respond to the JFreu spectator/admission vote. |
| `/message` | Use the configured JFreu message feature. |
| `/fake` | Administrative fake-message tool. |

Player-facing commands and administrative `/jfreu` subcommands have different
permission checks. Consult the in-game help instead of granting all controls to
ordinary players. JFreu `/yes` is distinct from the Jukebox/Voting `/y` command.

## Configuration

`app_defaults.toml` contains behavior, access/rank limits, messages and display
settings. Supported fields are editable through `//apps config jfreu`.

## Changes And Limits

Combines JFreu's gameplay and chat tools in one app. `/password` deliberately discloses a join password
to an already connected player; it does not reveal the XML-RPC SuperAdmin password.
This app is not the independent Sequential Info Messages scheduler.

## Credits

Original JFreu plugins: JFreu. XAseco updates: Xymph. Unspec fix: FuFi.
PyXaseco adaptation: Nila / PyXaseco project.
