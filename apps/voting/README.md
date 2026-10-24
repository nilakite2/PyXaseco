# Voting

## Purpose

Runs configurable chat-based votes for map/race actions and moderation, working
with Jukebox's shared yes-vote command and vote controls.

## Commands

| Command | Purpose |
| --- | --- |
| `/helpvote`, `/votehelp` | Show vote commands and rules. |
| `/skip`, `/replay`, `/endround` | Request a map skip, replay or round end. |
| `/ladder` | Request the supported ladder-limit vote. |
| `/ignore`, `/kick` | Request a moderation vote. |
| `/cancel` | Cancel a vote when permitted. |

`/y` is registered by Jukebox and participates in the shared voting path. F5/F6
buttons provide yes/no responses when shown. JFreu `/yes` and `/no` are a separate
spectator/admission voting feature.

## Configuration

`app_defaults.toml`, supported `//apps config voting` fields and shared server
settings control vote types, thresholds, cooldowns and restrictions. Available
votes depend on the loadout and game state; not every player can invoke every action.

## Changes And Limits

- Chat votes do not bypass configured administrative abilities or TMF rules.
- This app is distinct from native dedicated-server callvotes and ManiaKarma map
  ratings; enabling one does not automatically enable all three systems.

## Credits

RASP: Xymph and AssemblerManiac. XAseco voting plugin: Xymph.
PyXaseco adaptation: Nila / PyXaseco project.
