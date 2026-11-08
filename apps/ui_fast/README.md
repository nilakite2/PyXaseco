# FAST UI

Optional compact interface inspired by FAST 3, originally written by Gilles Masson
(Slig). Uses TMF's native panel skins and PyXaseco's existing records and commands.

## Enable

Move `app/ui_fast` from the disabled to the enabled list in `apps.toml`, then
restart with `//pyres`. Requires `platform_ui`, `ui` and `records_local`.

- `/uistyle list`: select **FAST**.
- `/uistyle 8`: select FAST directly with the default preset ID.
- `//uistyle default 8`: use FAST as the server default for inheriting players.
- `/uistyle default`: follow the server's default UI.
- `/fastui`: open the FAST menu when this style is active.
- `/fastui panels`: see which FAST panels are visible to you.
- `/fastui toggle <map|records|splits|team>`: hide or show a panel for this
  connection. This does not change anyone else's UI or re-enable a server-disabled panel.

Selection uses the existing saved player UI preference. Other players may keep
Classic or Modern. Loading this app does not change the server's default style.

## Interface

- Compact menu with nested navigation, existing permission checks and UI selection.
- Current map information; click to open the existing map-information window.
- One times panel with arrows to switch between available record sources.
- Click **Open list** for the selected source's existing records window.
- Leaders and nearby personal records, without blank filler rows.
- Live checkpoint number/time and difference against the player's personal best.
- Click the split comparison line to cycle **Best**, **Ideal** and a selected
  record reference. Reference uses the times panel's source and configured rank.
- Live checkpoint position in Rounds, Team, Laps and Cup; spectator tracking.
- Checkpoint gaps to the leader and nearby racers in those same modes.
- Estimated native Team round points and individual contributions.
- Optional manual-start, multi-map Team matches with totals and recent map history.
- F7 visibility and race/score transitions.

Trial, RPG, Dedimania, Ultimania and Mania Records are offered only when their apps
are loaded and their current-map data is available. This app does not submit
records or make additional external API requests.

## Configuration

Edit `app_defaults.toml` or use `//apps config ui_fast`. Position, width, rows,
refresh interval and score-screen visibility are configurable. Apply settings
with `//apps reload ui_fast`.

Menu, Map and Records each have their own `enabled` switch in this editor and in
`[ui_fast.menu]`, `[ui_fast.map]`, `[ui_fast.records]`. Turning one off clears only
its FAST panel and restores its standard counterpart, if enabled in the main UI
configuration. Other FAST components and Team match collection keep working.
Disabling Menu also closes its FAST popup and disables `/fastui` until re-enabled.
Live Splits already has its own switch; `competition.show_panel` hides only match
presentation, while `competition.enabled` controls the match service itself.
Configuration reload refreshes the affected widgets without a controller restart.

`[ui_fast.splits]` controls the live split display independently. Set `enabled`
to `false` to keep the existing checkpoint-delta widget instead. Position, width,
initial `comparison`, `reference_rank` and `show_position` can also be adjusted.

Best uses the fastest complete checkpoint sequence available in cached records
or session bests. Ideal combines the fastest sectors from those complete runs.
PB comparisons keep the previous best throughout an attempt; Laps uses lap-relative
times. Missing checkpoint data is shown as `--`, not a zero difference. Live
position compares checkpoint progress and elapsed time, not the Time Attack PB
leaderboard. Split display hides on the score screen and in Stunts.
Set `show_gaps = false` to hide the opponent lines. Time gaps compare the most
recent shared checkpoint or finish; if its time is unavailable, only the
checkpoint difference is known. No live race gaps are shown in Time Attack.

Preset ID **8** is the default, not a reserved ID. If it already belongs to a
custom style, choose an unused ID; existing styles are never overwritten.

## Team Competitions

Load `app/ui_fast`; nobody has to select the FAST style to participate.
`[ui_fast.competition]` controls availability, default team names and the FAST
history panel. Matches never start automatically. `ui_fast.enabled` controls
visuals only; `competition.enabled` independently controls the match service.

All controls require Admin or MasterAdmin. The existing admin-command lock applies
to `//tmatch`.

| Command | Purpose |
| --- | --- |
| `//tmatch start` | Create a match; start counting on the next fresh Team map. |
| `//tmatch status` | Show collection state, totals and the last five counted maps. |
| `//tmatch pause` | Pause collection and exclude the current unfinished map. |
| `//tmatch resume` | Resume a paused/stopped match on the next fresh Team map. |
| `//tmatch stop` | Stop collection; keep results available. |
| `//tmatch score <blue> <red>` | Correct overall totals; retain an adjustment entry. |
| `//tmatch team blue\|red <name>` | Rename a team for this match. |
| `//tmatch export [txt\|html]` | Write a server-local report with map scores and individual round history. |
| `//tmatch undo` | Request confirmation to remove the last counted map's contribution. |
| `//tmatch reset` | Request confirmation to clear the saved match. |

By default, scoring adds each completed map's final native Blue/Red points.
Choose `scoring = "map_wins"` to award one overall point to the map winner
(ties award neither team a point). A positive `target` and `win_margin` can
end overall collection automatically, e.g. target 5 with a two-point lead.
These settings are saved when a match starts, not retroactively applied to an
existing match. They never end or advance the native race.

A positive native Team points limit must be reached; skips below that limit,
warmups, restart callbacks and partial maps are excluded. Zero-limit/fixed-round
and custom scoring formats are not automatically counted. Replaying the same
map in a separate eligible attempt is allowed; duplicate end callbacks count once.
After a mid-map restart, that attempt is excluded until a new BeginChallenge.

State is saved atomically to `apps/ui_fast/team_match.json`, bound to the dedicated
server login. It contains map results, team names and score/name/undo adjustments;
no additional database is created. After a controller restart, an unfinished match
is paused: inspect `//tmatch status`, then explicitly resume. Back up the state file
if keeping completed match history before a reset. An unreadable file stops
collection instead of silently starting over.

`competition.show_round` controls the estimated Team round panel, even when
no match is collecting. `competition.round_history` controls whether completed
maps retain individual finishes, DNFs and estimated round points for reports.
Estimates use the native Team point cap and observed race order; they are not
used for match totals and are withheld when the roster or scoring basis is
uncertain. Up to 64 rounds per map are retained. Reports are written under
`apps/ui_fast/exports/`; they contain game logins and are not published.

When Match Overlay is installed, it shows these same totals and collection state;
its `mscore` and team-name controls update the match service. Without a saved match,
the overlay retains its original manual behaviour. Neither Match Overlay nor the
FAST history panel is required for collection. Native scores and playlists are
never changed by these commands.

FAST replaces the menu, map panel, compact records panels and checkpoint delta.
Other widgets and full command windows keep their existing presentation. FAST's
custom Team Relay/Laps/Rounds modes, native fixed-round/win-by-two overrides,
automatic false-start restarts and original database/administration system are
not ported. Multi-map Team scoring uses the service described above.

## Credits

FAST 3 UI design and original PHP source: Gilles Masson (Slig),
<https://github.com/Slig06/Fast3>. Python adaptation: PyXaseco contributors.
Distributed under PyXaseco's GNU GPL terms; see the controller's `LICENSE`.
