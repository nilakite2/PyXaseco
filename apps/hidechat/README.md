# Hide Chat

## Purpose

Optional port of schmidi's `plugin.hideChat.php` (2009).
Enable `app/hidechat` in the app loadout to use it; disabled by default.

## Commands

All players can select their own mode; administrator chat restrictions still apply.

- `/chat on`: show native chat.
- `/chat off`: hide native chat, including between races, until another mode is selected.
- `/chat auto`: hide after the first checkpoint, restore on finish, retirement,
  spectating, round end, map changes and the scoreboard.
- `/chat` or `/chat help`: show usage and the selected mode.
- The small close-style button cycles **On -> Auto -> Off -> On** and remains
  available when chat is hidden. F7 hides the button; commands still work.
- The FuFi HUD menu receives a Chat submenu when Hide Chat is enabled at menu load.

## Configuration

Settings live in `app_defaults.toml` and are editable through `//apps config hidechat`.
`default_mode` is used for new connections; existing session choices survive
configuration reloads and map changes. There is no database persistence.
`auto_rounds` optionally hides Auto chat from round start in Rounds/Team/Cup.
Public mode announcements are off by default. Button position/size are editable.

## Changes And Limits

The shared custom-UI service merges personal chat visibility into the existing HUD
settings, preserving native checkpoint/score/current-track controls. Administrator
chat restrictions take priority over `/chat on`; removing a restriction restores the
personal preference (or the configured UI setting if Hide Chat is not active).
Without the UI app, chat controls still work through native `custom_ui`.
Hiding the panel does not block chat delivery or suppress chat logs.

## Credits

Original Hide Chat: schmidi, based on code by slig.
PyXaseco adaptation: Nila / PyXaseco project.
