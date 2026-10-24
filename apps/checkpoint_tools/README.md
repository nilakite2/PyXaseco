# Checkpoint Tools

## Purpose

Combines the CP Live HUD and checkpoint standings/listing tools. Shows player
progress while racing and allows checkpoint-based comparisons while spectating.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/cplive` | Show CP Live help and available controls. | Everyone |
| `/cplive toggle`, `/cplive color` | Collapse the widget or change nickname presentation. | Everyone |
| `/cplive stats` | Show CP Live statistics. | Everyone |
| `/cplive enable`, `/cplive disable` | Enable/disable CP Live at runtime. | MasterAdmin |
| `/cp` | List current checkpoint standings. | Everyone |
| `/mycp` | List players at the same checkpoint count as you. | Everyone |
| `/cpll on\|off`, `/cpll filter on\|off` | Control the standings collector/spectator filter. | MasterAdmin |

CP Live help also describes server-wide row, refresh, leader and spectator controls
and their access requirements.

## Configuration

Use `app_defaults.toml` or `//apps config checkpoint_tools` for supported persistent
settings. Runtime chat controls are not a substitute for saving permanent defaults.

## Changes And Limits

- Shared delivery applies Classic/Modern styling on initial display as well as
  updates, and respects personal widget visibility.
- Live positions describe the current race, not persistent personal-best history.
- zTrack can consume checkpoint standings, but is an independent optional app.

## Credits

CP Live v3.4.3: join-red. Earlier versions: Lambda; Advanced v2: b4card1.
CPLL: ZiZa. PyXaseco adaptation: Nila / PyXaseco project.
