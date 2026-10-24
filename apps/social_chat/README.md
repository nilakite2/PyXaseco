# Social Chat

## Purpose

Provides private messages, private-message history, emotes and short social
shout-outs using the server's configured formatting.

## Commands

| Command | Purpose |
| --- | --- |
| `/pm <login-or-ID> <text>` | Send a private message. |
| `/pma <login-or-ID> <text>` | Send a message to a player and administrators. |
| `/pmlog` | View your recent private-message log. |
| `/me <text>` | Send an emote/action message. |
| `/hi`, `/bye`, `/thx`, `/lol`, `/lool` | Send the corresponding greeting/reaction. |
| `/brb`, `/afk`, `/gg`, `/gr`, `/n1`, `/bgm` | Send a short social/race reaction. |
| `/official` | Display the legacy informational response. |
| `/bootme` | Disconnect yourself from the server. |

Player-facing commands remain subject to server chat restrictions. Administrative
message/history tools live in Admin, not this public command surface.

## Configuration

Use `app_defaults.toml`, supported `//apps` settings and shared message templates
for the enabled social features and formatting.

## Changes And Limits

Groups RASP chat and emote commands as one app. Does not require Discord and is
not cross-server chat. Private messages are not end-to-end encrypted; configured
controller/admin logging can retain them. `/pma` deliberately includes admins.

## Credits

RASP: Xymph and AssemblerManiac. XAseco emote/message-log commands: Xymph.
PyXaseco adaptation: Nila / PyXaseco project.
