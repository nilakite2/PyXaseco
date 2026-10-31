# PyXaseco Apps

Each app guide explains its purpose, commands, configuration, changes and credits.

## Managing Apps

- `apps.toml` chooses the loadout. Use `app/<folder_name>` entries.
- MasterAdmins can use `//apps` to review apps and change supported settings.
- Enabling/disabling a loadout entry requires a controller restart. Reloading an
  app's configuration does not reload edited Python source.
- Where supplied, `app_defaults.toml` holds app settings. `//apps config <app>`
  edits supported fields; `//apps reload <app>` applies supported reloads.
- Configuration and Reload controls require an installed, enabled, loaded app.
  A missing app has no automatic download/install action yet.
- Dependencies and access checks still apply. An optional app is not required
  merely because it is listed here; check the installation's actual loadout.
- Credentials normally belong in the controller's `.env`; legacy `config.toml`
  remains supported. Individual guides identify exceptions.

## App Guides

| App | Purpose |
| --- | --- |
| [Admin](admin/README.md) | Server administration, maps, players and maintenance. |
| [Alternate Scoretable](alternate_scoretable/README.md) | Custom results and player details. |
| [Apps Manager](apps_manager/README.md) | Loadout and app configuration management. |
| [Best CP Times](best_cp_times/README.md) | Session checkpoint bests, shared or personal. |
| [Best CPs](bestcps/README.md) | Compact checkpoint-best widget. |
| [Best Finishes](bestfinishes/README.md) | Best finishes observed on this map. |
| [Best Runs](bestruns/README.md) | Run results with checkpoint information. |
| [Best Secs](bestsecs/README.md) | Persistent overall and personal sector records. |
| [Curated GPS](cgps/README.md) | Administrator-maintained GPS links. |
| [Checkpoint Tools](checkpoint_tools/README.md) | Live checkpoint positions and standings. |
| [DBTools](dbtools/README.md) | Optional local SQL backups. |
| [Discord](discord/README.md) | Outgoing chat and monitoring webhooks. |
| [Endless TMX Random](endlesstmxr/README.md) | Optional automatic random-map gameplay. |
| [FlexiTime](flexitime/README.md) | Flexible Time Attack limits. |
| [ForceMods](forcemods/README.md) | Server-wide environment and per-map mods. |
| [Help](help/README.md) | Registered command help. |
| [Hide Chat](hidechat/README.md) | Personal native-chat visibility. |
| [JFreu](jfreu/README.md) | Admission, spectator and server-message tools. |
| [Jukebox](jukebox/README.md) | Map lists, requests and TMX searches. |
| [Management Bridge](management_bridge/README.md) | Local Administrator Console connection. |
| [Match Overlay](match_overlay/README.md) | Team match/series scoreboard overlay. |
| [Platform Core](platform_core/README.md) | Shared database and gameplay services. |
| [Platform UI](platform_ui/README.md) | Styles, panels and personal preferences. |
| [Players](players/README.md) | Player statistics and server ranking. |
| [PYXA Stats](pyxa_stats/README.md) | Optional external statistics publisher. |
| [Quotes](quotes/README.md) | On-demand chat quotes. |
| [Dedimania Records](records_dedimania/README.md) | Dedimania records and submissions. |
| [Local Records](records_local/README.md) | Local PBs, records and record lists. |
| [Mania Records](records_wrmania/README.md) | WRMania submissions and fallback global-record widget. |
| [RPG Records](records_rpg/README.md) | RPG API records and replay uploads. |
| [Trial Records](records_trial/README.md) | Trial API records and finish submissions. |
| [Ultimania Records](records_ultimania/README.md) | Stunts records and replay submissions. |
| [Sequential Info Messages](seqinfomsg/README.md) | Rotating timed chat announcements. |
| [Server Info](server_info/README.md) | Server, runtime and integration information. |
| [Server Neighborhood](server_neighborhood/README.md) | Status and join links for linked local servers. |
| [ServerStats](serverstats/README.md) | Population history and optional SVG output. |
| [Social Chat](social_chat/README.md) | Private messages, emotes and shout-outs. |
| [Sponsor Banner](sponsor_banner/README.md) | Rotating clickable sponsor images. |
| [TMX](tmx/README.md) | TMX metadata, records and videos. |
| [UI](ui/README.md) | Records-Eyepiece, ManiaKarma and HUD menu. |
| [Voting](voting/README.md) | Chat-based server votes. |
| [zTrack](ztrack/README.md) | Checkpoint deltas against a selected record. |

## Credits

PyXaseco: Nila / PyXaseco project. Original app authors and contributors are listed
in each guide and the [project credits](../APP_CREDITS.md).
