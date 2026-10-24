# ServerStats

## Purpose

Records player/spectator population history and sampled peaks.
Optional SVG output provides a graph for an external browser or website.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/serverstats` | Show current counts, sampled peaks and averages. | Everyone |
| `/serverstats history` | Browse population history. | Everyone |
| `/serverstats help` | Show usage. | Everyone |

## Configuration

Enable `app/serverstats` and restart. Use `app_defaults.toml` or
`//apps config serverstats` for sampling, retention, grouping and graph settings.
Defaults: one sample every five minutes and seven days of history.

The `serverstats_samples` and `serverstats_peaks` tables are created automatically.
Set `graph.enabled = true` to write `stats/serverstats.svg`, or choose another
`.svg` path inside the controller folder.

## Changes And Limits

- Players and spectators are counted separately; rows are partitioned by server
  login so instances can share a database.
- Times are UTC. Averages use recorded samples; downtime is not counted as zero.
  Peaks are sampled values, not guaranteed maxima between observations.
- Retention removes old samples while keeping stored peaks. Disabling collection
  leaves database history intact.
- SVG output updates after samples. TMF ManiaLink cannot display SVG; serve/copy
  the file externally if wanted.
- Stores population counts, not player names/IPs. No web server or external API
  is needed. PYXA Stats publishing and `/server` health are separate features.

## Credits

Original ServerStats: [GB]-FlyveHest.
PyXaseco adaptation and SVG export: Nila / PyXaseco project.
