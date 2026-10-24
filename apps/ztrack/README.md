# zTrack

## Purpose

Shows checkpoint deltas against a selected local or Dedimania record, for yourself
or the player you are spectating.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/ztrack` | Show usage. | Everyone |
| `/ztrack local <rank>` | Compare against a local leaderboard record. | Everyone |
| `/ztrack dedi <rank>` | Compare against an available Dedimania record. | Everyone |
| `/ztrack off` | Disable your comparison overlay. | Everyone |

Ranks are one-based leaderboard positions, not database IDs or player IDs.

## Configuration

Optional `app/ztrack`; no app-specific defaults file. Uses shared checkpoint
tracking/standings and the selected provider's existing record data. Dedimania
comparison requires that optional provider and checkpoint data for the target.

## Changes And Limits

- Uses the shared UI delivery path, with spectator-target handling rather than
  comparing a spectator's nonexistent current run.
- A record without checkpoint splits cannot be used as a comparison target.
- Reads existing record splits; it does not create a new persistent personal
  checkpoint-history database or replace Best CP Times/Best Secs.

## Credits

Original zTrack: ZiZa.
PyXaseco adaptation: Nila / PyXaseco project.
