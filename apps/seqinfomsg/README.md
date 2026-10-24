# Sequential Info Messages

## Purpose

Broadcasts configured chat messages in sequence at a fixed interval.

## Commands

All `/seq` commands require Admin or MasterAdmin.

| Command | Purpose |
| --- | --- |
| `/seq`, `/seq help` | Show usage. |
| `/seq list` | Browse messages and IDs. |
| `/seq add <text>` | Add a message using the lowest free positive ID. |
| `/seq mod <id> <text>` | Edit a message. |
| `/seq rem <id>`, `/seq del <id>` | Delete a message. |

## Configuration

Enable `app/seqinfomsg` and restart. In `app_defaults.toml`:

```toml
[seqinfomsg]
enabled = true
interval_seconds = 120

[seqinfomsg.messages]
message_01 = '$fffWelcome to the server!'
message_02 = '$l[http://example.com]Visit our website$l'
```

Use `//apps config seqinfomsg` for enabled/interval settings, or
`//apps reload seqinfomsg` after direct file edits.

## Changes And Limits

- Command edits save and apply immediately, preserving TMF formatting and spacing.
- IDs remain stable. New messages fill the earliest gap; an empty list restarts at 1.
  Exact TOML row keys also work in edit/delete commands.
- Numbered messages follow ID order; named rows follow them in file order.
  Blank rows are skipped; an empty list sends nothing.
- The sequence starts on the first timer tick after startup/reload. Map changes
  do not reset it; delayed ticks do not send a burst of missed messages.
- Messages repeat after the last entry. Invalid/non-positive intervals use 30 seconds.

## Credits

Original Sequential Info Messages: FuFi.
PyXaseco adaptation and message-management commands: Nila / PyXaseco project.
