# PyXaseco Validated Pack Notes

This file is the internal status sheet for the validated pack in this folder.

Use this document when you want to know:
- what this pack currently loads by default
- which plugins are included but disabled
- which parts are considered validated vs still optional or in-progress

For a cleaner public project overview, use [README.md](README.md).

## Scope

This pack is aimed at **TrackMania Forever** servers running on the current Python 3.12 PyXaseco core included here.

It includes:
- the PyXaseco controller
- the validated XML configuration set
- the currently preferred plugin loadout from `plugins.xml`
- an optional standalone Discord bot in `DiscordBot-optional/`

## Validated default loadout

The following plugins are enabled in [plugins.xml](plugins.xml).

| Plugin | Status | Current role / notes |
|---|---|---|
| `plugin_localdatabase` | Enabled, required | Local player, challenge, record, and schema maintenance layer. Also handles extra challenge metadata support. |
| `plugin_rounds` | Enabled | Rounds/points helper used by score-related features. |
| `chat_admin` | Enabled | Main admin command set, including map control, role management, and server method calls. |
| `plugin_server_admin_bridge` | Enabled | Whitelists the server login as MasterAdmin for trusted automation/server-side command flows. |
| `plugin_discord_webhook` | Enabled, optional to configure | Outbound Discord webhook bridge for admin logs and player chat. Config: `discord_webhook.xml`. |
| `chat_help` | Enabled | Help command set. |
| `chat_records` | Enabled | Record-related chat commands. |
| `chat_records2` | Enabled | Additional record windows and list views. |
| `chat_recrels` | Enabled | Personal-best and record relation commands. |
| `chat_dedimania` | Enabled | Dedimania chat commands and stats windows. |
| `chat_players` | Enabled | Main `/players` functionality. |
| `chat_players2` | Enabled | Extended player list / clan-style list helpers. |
| `chat_wins` | Enabled | Win statistics commands. |
| `chat_laston` | Enabled | Last-seen player lookup. |
| `chat_lastwin` | Enabled | Last-win lookup. |
| `chat_stats` | Enabled | General player/server stat commands. |
| `chat_server` | Enabled | Server info and server-side utility commands. |
| `chat_songmod` | Enabled | Song/mod related helpers. |
| `chat_me` | Enabled | Simple `/me` style chat helper. |
| `plugin_tmxinfo` | Enabled | TMX metadata, `/tmxinfo`, `/tmxrecs`, shared TMX helpers used by other plugins. |
| `plugin_track` | Enabled | Track information/chat helpers and TMX-aware track links. |
| `plugin_checkpoints` | Enabled | Checkpoint info commands. |
| `plugin_dedimania` | Enabled | Dedimania integration. |
| `plugin_rasp` | Enabled | Base RASP logic and shared settings. |
| `plugin_rasp_jukebox` | Enabled | Jukebox, `/list`, TMX add/search, autojuke, tracklist-related logic. |
| `plugin_rasp_chat` | Enabled | RASP chat presentation helpers. |
| `plugin_rasp_nextmap` | Enabled | `/nextmap` and next track messaging. |
| `plugin_rasp_nextrank` | Enabled | Next-rank helper logic. |
| `plugin_rasp_votes` | Enabled | Public vote handling. Can be disabled through `rasp.xml` vote settings without unloading the plugin. |
| `plugin_chatlog` | Enabled | Chat logging and chat log windows. |
| `plugin_style` | Enabled | Shared style / ManiaLink style loading. |
| `plugin_panels` | Enabled | Panel loader/manager for admin, donate, records, and vote panels. |
| `plugin_donate` | Enabled | Donate panel and donate-related commands. |
| `plugin_uptodate` | Enabled | Update-check style helper. |
| `plugin_rpoints` | Enabled | Round points presets and `/admin rpoints ...` management. |
| `jfreu_plugin` | Enabled | Join/leave, ranking, moderation, and welcome-flow functionality. |
| `plugin_records_eyepiece` | Enabled | Main records widget/window suite. Current validated baseline is strongest in TA; non-TA layout work is improved but still the area to watch first when testing edge cases. |
| `plugin_cplive_v3` | Enabled | Checkpoints Live widget. |
| `plugin_banner` | Enabled | Small banner showing the live server name. |
| `plugin_bestfinishes` | Enabled | Best-finishes widget inspired by the original BestRuns idea, but functionally diverged at this point rather than being just a rename. |
| `plugin_mania_karma` | Enabled | ManiaKarma voting, windows, reminders, and TMX map opinion features. |
| `plugin_fufi_menu` | Enabled | FuFi/JFreu menu integration. |
| `plugin_cpll` | Enabled | Companion to `plugin_ztrack`, focused on checkpoint tracking via `/cp`. |
| `plugin_ztrack` | Enabled | Local/Dedimania comparison helper used for comparing your current run against stored runs/times. |

## Included but disabled by default

These are shipped in the pack but commented out in [plugins.xml](plugins.xml).

| Plugin | Status | Notes |
|---|---|---|
| `plugin_bestsecs` | Included, disabled | Best sector times widget. |
| `plugin_bestcps` | Included, disabled | Best CPs widget. |
| `plugin_tgj_allbutton` | Included, disabled | Custom button plugin. |
| `plugin_best_checkpoint_times` | Included, disabled | Alternative checkpoint-times widget/plugin. |
| `plugin_freezone` | Included, disabled | FreeZone/Nations/TMNF support plugin. |
| `plugin_flexitime` | Included, disabled | TA-only FlexiTime plugin. Should not be used outside TimeAttack. |
| `plugin_stalker_tools` | Included, disabled | STALKER Tools extended commands and menu helpers. |
| `plugin_stalker_actionids` | Included, disabled | STALKER action-id companion plugin. |

## Legacy or alternate files still present in `plugins/`

These files exist in the tree but are **not** part of the preferred validated loadout:

| File | Status | Notes |
|---|---|---|
| `plugin_bestruns.py` | Present, alternate | Original-style BestRuns implementation that still works 1:1 with the XAseco behavior. |
| `mistral_idlekick.py` | Present, not wired by default | Not part of the default validated plugin list. |
| `plugin_msglog.py` | Present, not wired by default | Not part of the default validated plugin list. |
| `plugin_access.py` | Present, not wired by default | Access-control helper available if needed. |
| `plugin_autotime.py` | Present, not wired by default | Extra timing helper not enabled by default. |
| `plugin_muting.py` | Present, not wired by default | Separate muting helper not enabled by default. |
| `plugin_rasp_karma.py` | Present, not wired by default | Separate RASP karma helper not enabled by default. |

## Optional Discord pieces

### Outbound webhook bridge

Enabled by default in `plugins.xml`, but inactive until configured:
- [plugin_discord_webhook.py](plugins/plugin_discord_webhook.py)
- [discord_webhook.xml](discord_webhook.xml)

Current scope:
- admin logs
- player chat
- joins/leaves
- new challenge messages
- warnings/errors

### Standalone Discord bot

Optional folder:
- [DiscordBot-optional](DiscordBot-optional)

Current purpose:
- listen in configured Discord guild/channel routes
- parse commands like `-tm1 hello`
- route them to configured TrackMania server ids
- send chat into the dedicated server

See:
- [DiscordBot-optional/README.md](DiscordBot-optional/README.md)
- [DiscordBot-optional/servers.yaml.example](DiscordBot-optional/servers.yaml.example)

## Configuration files worth checking first

- `config.xml`
- `plugins.xml`
- `adminops.xml`
- `localdatabase.xml`
- `dedimania.xml`
- `mania_karma.xml`
- `rasp.xml`
- `records_eyepiece.xml`
- `discord_webhook.xml`
- `bestfinishes.xml`
- `bestcps.xml`
- `bestsecs.xml`

## Database notes

This pack still ships the base schema in `database/pyxaseco_default_schema.sql`, and importing that schema before first real use is still the recommended path.

Compared with older snapshots, the current controller does more automatic maintenance than before:
- startup schema checks/repairs for several controller-owned tables
- charset widening/repair for problem tables where needed
- support for extra challenge metadata through `challenges_extra`

That means the current pack is much better at repairing or extending an existing DB than the very early alpha builds were. It has already been validated successfully against multiple older XAseco-style databases, so reusing an existing DB is a realistic normal path here. For a brand-new setup, importing the shipped schema is still the cleanest starting point.

## Practical validation notes

This pack is a strong baseline, but these are still the areas most worth retesting after custom changes:
- non-TA Eyepiece layouts
- rarely used optional plugins that are disabled by default
- server-specific admin permission setups
- ManiaLink text rendering when unusual nicknames or quotes are involved
- Discord-side integrations after route/config edits

## Short version

If you want the current intended baseline:
- use the enabled set from `plugins.xml`
- treat `plugin_bestfinishes` as the active BestRuns successor
- treat Eyepiece as validated enough for daily use, with TA being the strongest tested mode
- use `plugin_discord_webhook` for outbound Discord mirroring
- use `DiscordBot-optional/` only if you want Discord-to-server chat bridging
