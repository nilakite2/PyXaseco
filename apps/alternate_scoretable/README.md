# Alternate Scoretable

## Purpose

Displays custom race results and player details using Classic/Modern styling.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/scoretable` | Open the results window. | Everyone |
| `/scoretable help` | Explain the columns and controls. | Everyone |

The Rankings bar button opens the same window. Click a player for details.

## Configuration

Enable `app/alternate_scoretable` in `apps.toml` and restart.
Use `app_defaults.toml` or `//apps config alternate_scoretable` for rows, columns,
automatic display, timing and the bar button's position/size.
Finish popups default to a three-second delay and eight-second duration;
end-of-map popups default to a five-second delay and twenty-second duration.

## Changes And Limits

- Time Attack displays best times; Rounds/Cup/Stunts display points; Laps uses
  checkpoint progress. Team totals are shown separately from individual results.
- PBs use saved local records, including results beyond the leaderboard limit.
  Finish counts and session bests cover the current map since app startup.
- Automatic display replaces the corresponding native score panels. Closing,
  expiry, F7 or disabling the app restores their configured visibility.
- F7 hides the bar button and closes the window; `/scoretable` remains available.
- Ladder rank is cached Nadeo rank. Ladder-point gains, player avatars and the
  original plugin's custom place announcements are not included.
- No additional database table or external service is required.

## Credits

Original Alternate Scoretable: undef.de.
PyXaseco adaptation: Nila / PyXaseco project.
