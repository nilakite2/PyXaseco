# zTrack

## Purpose

Shows checkpoint or sector deltas against a selected record, for yourself or the
player you are spectating. Automatic selection uses Dedi -> Local -> WRMania,
skipping unavailable providers and records without usable complete splits.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/ztrack` | Show usage. | Everyone |
| `/ztrack auto [rank]` or `/ztrack <rank>` | Automatically choose Dedi, then Local, then WRMania. Default rank: 1. | Everyone |
| `/ztrack local <rank>` | Compare against a local leaderboard record. | Everyone |
| `/ztrack dedi <rank>` | Compare against an available Dedimania record. | Everyone |
| `/ztrack wrm <rank>` | Compare against WRMania when that optional app is loaded. Alias: `wrmania`. | Everyone |
| `/ztrack auto <rank> sector` | Compare individual sector times rather than cumulative CP times. Also works with explicit sources. | Everyone |
| `/ztrack cps [source] [rank]` | List the chosen record's cumulative checkpoint times. Source defaults to auto, rank to 1. | Everyone |
| `/ztrack sectors [source] [rank]` | List individual sector times. | Everyone |
| `/ztrack off` | Disable your comparison overlay. | Everyone |

Ranks are one-based leaderboard positions, not database IDs or player IDs.
Explicit `local`, `dedi` and `wrm` selections stay on that source. Auto can switch
providers as availability changes, using the same requested rank. The overlay
shows the actual source. Missing data clears the old delta instead of leaving it visible.

## Configuration

Optional `app/ztrack`; no app-specific defaults file. Uses shared checkpoint
tracking/standings and the selected provider's existing record data. Dedimania
comparison requires that optional provider and checkpoint data for the target.
WRMania is optional too: zTrack neither imports that package nor declares it as
a dependency. It continues working if the entire WRMania folder is absent.
Comparisons use existing caches; they do not make network requests.

## Changes And Limits

- Uses the shared UI delivery path, with spectator-target handling rather than
  comparing a spectator's nonexistent current run.
- A record without checkpoint splits cannot be used as a comparison target.
- Reads existing record splits; it does not create a new persistent personal
  checkpoint-history database or replace Best CP Times/Best Secs.
- Sector comparison uses adjacent checkpoints from the same run. Missing or
  out-of-order checkpoints do not produce a guessed sector time. Laps compare
  lap-relative splits and resynchronise at a known lap boundary after a gap.

## Credits

Original zTrack: ZiZa.
PyXaseco adaptation: Nila / PyXaseco project.
