# Discord

## Purpose

Optional outbound Discord integration for server monitoring/administrative events
and chat forwarding. The webhook service owns delivery independently of gameplay.

## Commands

No direct chat command. Configuration and reload controls are available through
`//apps` where supported; there is no in-game Discord bot command interface.

## Configuration

Enable `app/discord` only where wanted. Configure webhook destinations through
the controller's `.env`, including `DISCORD_ADMIN_WEBHOOK_URL` and
`DISCORD_CHAT_WEBHOOK_URL`. App behavior is in `app_defaults.toml`.
Keep webhook URLs private: possession can permit posting to their channels.

## Changes And Limits

- Webhook work uses the controller's external-delivery service rather than making
  each gameplay callback perform an unbounded network request.
- This is outgoing integration, not an inbound remote-administration bot.
- Forwarded chat/events can contain player logins and nicknames; enable only for
  channels that should receive that data.
- The Join Discord HUD link is a UI configuration feature, not dependent on this
  webhook app. Other controller apps do not require Discord.

## Credits

Nila / PyXaseco project.
