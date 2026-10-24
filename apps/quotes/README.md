# Quotes

## Purpose

Broadcasts saved quotes on demand. Quotes are stored in `app_defaults.toml`;
there is no automatic timer.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/quote` | Broadcast a random quote. | Everyone |
| `/quote <id>` | Broadcast a specific quote. | Everyone |
| `/quote help`, `/quote list` | Show help or browse quotes. | Everyone |
| `/quote add <text>` | Add a quote. | Admin / MasterAdmin |
| `/quote mod <id> <text>` | Edit a quote. | Admin / MasterAdmin |
| `/quote rem <id>`, `/quote del <id>` | Delete a quote. | Admin / MasterAdmin |

## Configuration

Enable `app/quotes` and restart. `//apps config quotes` edits enabled/cooldown
settings. Quote text can be edited through the commands or `[quotes.messages]`
rows such as `message_01` in `app_defaults.toml`.
Reload after direct file edits with `//apps reload quotes`.

## Changes And Limits

- Broadcast format: `$39f[QUOTE #<id>] $fff<quote_text>`.
- Additions reuse the lowest free positive ID without renumbering other quotes.
- Command edits save and apply immediately. TMF formatting and internal spacing
  are preserved.
- Public broadcasts have a per-player cooldown, five seconds by default.
  Help, listing and editing do not broadcast quotes.

## Credits

Nila / PyXaseco project.
