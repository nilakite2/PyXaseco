# Discord Bot - TM ChatBot

This folder contains the Discord chat bot for TrackMania PyXaseco controller.

You must create this app on https://discord.com/developers/applications/ for it to run.

Current intended responsibility:
- listen for Discord messages in configured guild/channel routes
- parse commands like `-tm1 hello world`
- map `tm1`, `tm2`, `tm3`, ... to configured server ids
- use its own standalone `servers.yaml`

Current structure:
- `bot.py`
- `config.py` - shared `servers.yaml` loader
- `commands.py` - `-tm1` / `-tm2` command parsing helpers
- `bridge.py` - bridge interface

Command format:
- `-tm1 hello world` -> send `hello world` to instance with `bot_id: 1`
- `-tm5 restart soon` -> send `restart soon` to instance with `bot_id: 5`

Routing is controlled in `servers.yaml` inside this folder:
- `settings.discord_bot.routes[].guild_id`
- `settings.discord_bot.routes[].channel_id`
- `settings.discord_bot.routes[].allowed_server_ids`

Config loading:
- default: `servers.yaml`
- optional override: `DISCORD_BOT_SERVERS_YAML=/path/to/servers.yaml`
- local environment file: `.env`

Environment:
- `DISCORD_BOT_TOKEN=...`
- optional `DISCORD_BOT_SERVERS_YAML=...`
