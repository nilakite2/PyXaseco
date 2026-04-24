from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..config import _state

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Action / Manialink constants
# ---------------------------------------------------------------------------

ACTION_TOGGLE = 382009003

ML_WINDOW = 91800
ML_SUBWIN = 91801
ML_TOGGLE = 91802

TL_PREV_BASE = 9181000   # prev page: -(TL_PREV_BASE + page)
TL_NEXT_BASE = 9181000   # next page: TL_NEXT_BASE + page + 1
TL_JB_BASE   = 9182000    # jukebox:   TL_JB_BASE + global_idx (1-based)
TL_DROP_BASE = 2000       # drop jb:   -(TL_DROP_BASE + jb_pos)


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

async def _on_manialink_answer(aseco: 'Aseco', answer: list):
    """
    Port of the _on_manialink_answer().

    This module only routes actions. Actual builders / senders live in the
    split chat/widget modules.
    """
    if len(answer) < 3:
        return

    try:
        action = int(answer[2])
    except Exception:
        return

    login = answer[1]
    player = aseco.server.players.get_player(login)
    if not player:
        return

    # Delayed imports to avoid circular dependencies between split modules.
    from .chat import chat_togglewidgets
    from ..tracklist import (
        _send_tracklist_window,
        _close_tracklist_window,
        _build_tracklist_window,
        _build_tracklist_filter_window,
        _build_tracklist_sorting_window,
        _send_trackauthorlist_window,
        _build_trackauthorlist_window,
    )
    from ..widgets.challenge import _open_challenge_window
    from ..widgets.records_local import _build_local_records_window
    from ..widgets.records_dedi import _build_dedi_records_window
    from ..widgets.live import _build_live_rankings_window
    from ..helpwin import _build_help_window
    from ..toplists import _build_generic_toplist_window, _build_top_nations_window, _build_toplist_window, draw_all_score_columns, hide_all_score_columns
    from ..widgets.common import _send, _send_chat

    # ── TracklistWindow: close ──────────────────────────────────────────────
    if action == ML_WINDOW:
        await _close_tracklist_window(aseco, login)
        return

    # ── TracklistWindow: pagination prev (negative) ────────────────────────
    if -TL_PREV_BASE - 250 <= action < -TL_PREV_BASE + 1 and action < 0:
        page = abs(action) - TL_PREV_BASE - 1
        if getattr(player, '_tl_tracks', None) is not None:
            await _send_tracklist_window(
                aseco,
                player,
                page=page,
                filter_cmd=getattr(player, '_tl_filter', ''),
                search=getattr(player, '_tl_search', ''),
            )
        return

    # ── TracklistWindow: pagination next (positive) ────────────────────────
    if TL_NEXT_BASE <= action <= TL_NEXT_BASE + 250:
        page = action - TL_NEXT_BASE
        if getattr(player, '_tl_tracks', None) is not None:
            await _send_tracklist_window(
                aseco,
                player,
                page=page,
                filter_cmd=getattr(player, '_tl_filter', ''),
                search=getattr(player, '_tl_search', ''),
            )
        return

    # ── TracklistWindow: jukebox a track (TL_JB_BASE + idx) ───────────────
    if TL_JB_BASE < action <= TL_JB_BASE + 5000:
        global_idx = action - TL_JB_BASE
        tracks = getattr(player, '_tl_tracks', [])

        if 1 <= global_idx <= len(tracks):
            player.tracklist = [{
                'uid': t['uid'],
                'name': t['name'],
                'author': t['author'],
                'environment': t['env'],
                'filename': t['filename'],
            } for t in tracks]

            try:
                from pyxaseco.plugins.plugin_rasp_jukebox import chat_jukebox
                await chat_jukebox(aseco, {'author': player, 'params': str(global_idx)})
            except Exception as e:
                logger.debug('[Eyepiece] TL jukebox click: %s', e)

            await _send_tracklist_window(
                aseco,
                player,
                page=getattr(player, '_tl_page', 0),
                filter_cmd=getattr(player, '_tl_filter', ''),
                search=getattr(player, '_tl_search', ''),
            )
        return

    # ── TracklistWindow: drop from jukebox (negative, < -TL_DROP_BASE) ────
    if -(TL_DROP_BASE + 100) <= action < -TL_DROP_BASE:
        jb_pos = abs(action) - TL_DROP_BASE

        try:
            from pyxaseco.plugins.chat_admin import chat_admin
            await chat_admin(aseco, {'author': player, 'params': f'dropjukebox {jb_pos}'})
        except Exception as e:
            logger.debug('[Eyepiece] TL dropjukebox: %s', e)

        await _send_tracklist_window(
            aseco,
            player,
            page=getattr(player, '_tl_page', 0),
            filter_cmd=getattr(player, '_tl_filter', ''),
            search=getattr(player, '_tl_search', ''),
        )
        return

    # ── /estat pagination: local records ───────────────────────────────────
    if -918149 <= action <= -918100:
        page = abs(action) - 918100
        xml = await _build_local_records_window(aseco, page)
        if xml:
            await _send(aseco, login, xml)
        return

    # 91803 = Clock widget clicked -> open worldmap timezone picker
    if action == 91803:
        from ..widgets.clock_tz import open_clock_window
        await open_clock_window(aseco, login)
        return

    # 918300-918319 = Select a timezone region group
    if 918300 <= action <= 918319:
        from ..widgets.clock_tz import open_clock_group
        await open_clock_group(aseco, login, action - 918300)
        return

    # 918350-918799 = Select a specific timezone
    if 918350 <= action <= 918799:
        from ..widgets.clock_tz import select_timezone
        await select_timezone(aseco, login, action - 918350)
        return

    if 918100 <= action <= 918149:
        page = action - 918100
        xml = await _build_local_records_window(aseco, page)
        if xml:
            await _send(aseco, login, xml)
        return

    # ── /estat pagination: dedi records ────────────────────────────────────
    if -918300 <= action <= -918200:
        page = abs(action) - 918200
        xml = _build_dedi_records_window(aseco, page)
        if xml:
            await _send(aseco, login, xml)
        return

    if 918200 <= action < 918300:
        page = action - 918200
        xml = _build_dedi_records_window(aseco, page)
        if xml:
            await _send(aseco, login, xml)
        return

    # ── ManialinkId-based actions (918xx) ──────────────────────────────────

    # 91802 = ML_TOGGLE (challenge widget click -> challenge window)
    if action == ML_TOGGLE:
        await _open_challenge_window(aseco, login)
        return

    # 91804 = Show DedimaniaRecordsWindow
    if action == 91804:
        from ..widgets.records_dedi import _get_dedi_records
        recs = _get_dedi_records()
        if recs:
            xml = _build_dedi_records_window(aseco, 0, records=recs)
            await _send(aseco, login, xml)
        else:
            await _send_chat(aseco, login, '{#server}> {#error}No Dedimania records available.')
        return

    # 91805 = Show LocalRecordsWindow
    if action == 91805:
        xml = await _build_local_records_window(aseco, 0)
        if xml:
            await _send(aseco, login, xml)
        else:
            await _send_chat(aseco, login, '{#server}> {#error}No Local records available.')
        return

    # 91806 = Show LiveRankingsWindow
    if action == 91806:
        xml = _build_live_rankings_window(aseco, 0)
        if xml:
            await _send(aseco, login, xml)
        return

    # 91808 = Trigger /tmxinfo
    if action == 91808:
        try:
            from pyxaseco.plugins.plugin_tmxinfo import chat_tmxinfo
            await chat_tmxinfo(aseco, {'author': player, 'params': ''})
        except Exception as e:
            logger.debug('[Eyepiece] TMX info click: %s', e)
        return

    # 5834288 = Force spectator back into play mode
    if action == 5834288:
        try:
            await aseco.client.query('ForceSpectator', login, 2)
            await aseco.client.query('ForceSpectator', login, 0)
        except Exception as e:
            logger.debug('[Eyepiece] Force Play click: %s', e)
        return

    # 91809 = Show TopNationsWindow
    if action == 91809:
        xml = await _build_top_nations_window(aseco)
        if xml:
            await _send(aseco, login, xml)
        else:
            await _send_chat(aseco, login, '{#server}> {#error}No nation statistics available.')
        return

    # 91810 = Show TopRankingsWindow
    if action == 91810:
        xml = await _build_generic_toplist_window(aseco, 'TOPRANKS')
        if xml:
            await _send(aseco, login, xml)
        return

    # 91811 = Show TopWinnersWindow
    if action == 91811:
        xml = await _build_generic_toplist_window(aseco, 'TOPWINNERS')
        if xml:
            await _send(aseco, login, xml)
        return

    # 91812 = Show MostRecordsWindow
    if action == 91812:
        xml = await _build_generic_toplist_window(aseco, 'MOSTRECORDS')
        if xml:
            await _send(aseco, login, xml)
        return

    # 91813 = Show MostFinishedWindow
    if action == 91813:
        xml = await _build_generic_toplist_window(aseco, 'MOSTFINISHED')
        if xml:
            await _send(aseco, login, xml)
        return

    # 91814 = Show TopPlaytimeWindow
    if action == 91814:
        xml = await _build_generic_toplist_window(aseco, 'TOPPLAYTIME')
        if xml:
            await _send(aseco, login, xml)
        return


    # 91815 = Show TopDonatorsWindow
    if action == 91815:
        xml = await _build_generic_toplist_window(aseco, 'TOPDONATORS')
        if xml:
            await _send(aseco, login, xml)
        return

    # 91816 = Show TopTracksWindow
    if action == 91816:
        xml = await _build_generic_toplist_window(aseco, 'TOPTRACKS')
        if xml:
            await _send(aseco, login, xml)
        return

    # 91817 = Show TopVotersWindow (karma votes)
    if action == 91817:
        xml = await _build_generic_toplist_window(aseco, 'TOPVOTERS')
        if xml:
            await _send(aseco, login, xml)
        return


    # 918158 = Show TopRoundscoreWindow
    if action == 918158:
        xml = await _build_generic_toplist_window(aseco, 'TOPROUNDSCORE')
        if xml:
            await _send(aseco, login, xml)
        return

    # 918159 = Show TopVisitorsWindow (PHP id)
    if action == 918159:
        xml = await _build_generic_toplist_window(aseco, 'TOPVISITORS')
        if xml:
            await _send(aseco, login, xml)
        return

    # 91899 = Show TopWinningPayoutsWindow
    if action == 91899:
        xml = await _build_generic_toplist_window(aseco, 'TOPWINNINGPAYOUTS')
        if xml:
            await _send(aseco, login, xml)
        return

    # 91819 = Show TopVisitorsWindow
    if action == 91819:
        xml = await _build_generic_toplist_window(aseco, 'TOPVISITORS')
        if xml:
            await _send(aseco, login, xml)
        return

    # 918153 = Show ToplistWindow
    if action == 918153:
        xml = await _build_toplist_window(aseco, login, page=0)
        if xml:
            await _send(aseco, login, xml)
        return

    # 91820 = Open TracklistWindow (no filter)
    if action == 91820:
        await _send_tracklist_window(aseco, player, page=0)
        return

    # 91821 = Show TracklistFilterWindow
    if action == 91821:
        xml = _build_tracklist_filter_window(aseco, player)
        await _send(aseco, login, xml)
        return

    # 91840 = Tracklist filter: Jukebox only
    if action == 91840:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='JUKEBOX')
        return

    # 91841 = Tracklist filter: No recent
    if action == 91841:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='NORECENT')
        return

    # 91842 = Tracklist filter: Only recent
    if action == 91842:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='ONLYRECENT')
        return

    # 91843 = Tracklist filter: No rank
    if action == 91843:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='NORANK')
        return

    # 91844 = Tracklist filter: Only ranked
    if action == 91844:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='ONLYRANK')
        return

    # 91846 = Tracklist filter: No author time
    if action == 91846:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='NOAUTHOR')
        return

    # 91855 = Show TracklistSortingWindow
    if action == 91855:
        xml = _build_tracklist_sorting_window(aseco)
        await _send(aseco, login, xml)
        return

    # 91856 = Show TrackauthorlistWindow
    if action == 91856:
        await _send_trackauthorlist_window(aseco, player, page=0)
        return

    # 91857 = Tracklist filter: Not finished
    if action == 91857:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='NOFINISH')
        return

    # 918157 = Show HelpWindow
    if action == 918157:
        xml = _build_help_window(aseco)
        await _send(aseco, login, xml)
        return

    # 91870 = Tracklist: Best ranked
    if action == 91870:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='BEST')
        return

    # 91871 = Tracklist: Worst ranked
    if action == 91871:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='WORST')
        return

    # 91872 = Tracklist: Shortest
    if action == 91872:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='SHORTEST')
        return

    # 91873 = Tracklist: Longest
    if action == 91873:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='LONGEST')
        return

    # 91874 = Tracklist: Newest
    if action == 91874:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='NEWEST')
        return

    # 91875 = Tracklist: Oldest
    if action == 91875:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='OLDEST')
        return

    # 91876 = Tracklist: Sort by track name
    if action == 91876:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='TRACK')
        return

    # 91877 = Tracklist: Author list window
    if action == 91877:
        await _send_trackauthorlist_window(aseco, player, page=0)
        return

    # 91878 = Tracklist: Best karma
    if action == 91878:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='BESTKARMA')
        return

    # 91879 = Tracklist: Worst karma
    if action == 91879:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='WORSTKARMA')
        return


    # 91822-91828 = environment filters
    if action == 91822:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='STADIUM')
        return
    if action == 91823:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='BAY')
        return
    if action == 91824:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='COAST')
        return
    if action == 91825:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='DESERT')
        return
    if action == 91826:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='ISLAND')
        return
    if action == 91827:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='RALLY')
        return
    if action == 91828:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='ALPINE')
        return

    # 91845-91854 = medal / mood / multilap filters
    if action == 91845:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='NOGOLD')
        return
    if action == 91847:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='SUNRISE')
        return
    if action == 91848:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='DAY')
        return
    if action == 91849:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='SUNSET')
        return
    if action == 91850:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='NIGHT')
        return
    if action == 91851:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='MULTILAP')
        return
    if action == 91852:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='NOMULTILAP')
        return
    if action == 91853:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='NOSILVER')
        return
    if action == 91854:
        await _send_tracklist_window(aseco, player, page=0, filter_cmd='NOBRONZE')
        return

    # 91898 = Top Active Players
    if action == 91898:
        xml = await _build_generic_toplist_window(aseco, 'TOPACTIVE')
        if xml:
            await _send(aseco, login, xml)
        return

    # Live rankings window pagination: 91815x range
    if 918150 <= action <= 918152:
        page = action - 918150
        xml = _build_live_rankings_window(aseco, page)
        if xml:
            await _send(aseco, login, xml)
        return

    if -918152 <= action <= -918150:
        page = abs(action) - 918150
        xml = _build_live_rankings_window(aseco, page)
        if xml:
            await _send(aseco, login, xml)
        return

    # ToplistWindow pagination
    if 9187250 <= action <= 9187259:
        page = action - 9187250
        xml = await _build_toplist_window(aseco, login, page)
        if xml:
            await _send(aseco, login, xml)
        return
    
    if -9187259 <= action <= -9187250:
        page = abs(action) - 9187250
        xml = await _build_toplist_window(aseco, login, page)
        if xml:
            await _send(aseco, login, xml)
        return

    # Help window pagination: 91816x range
    if 918160 <= action <= 918164:
        page = action - 918160
        xml = _build_help_window(aseco, page)
        await _send(aseco, login, xml)
        return

    if -918164 <= action <= -918160:
        page = abs(action) - 918160
        xml = _build_help_window(aseco, page)
        await _send(aseco, login, xml)
        return


    # TrackauthorlistWindow pagination: 9187000 range
    if 9187000 <= action <= 9187249:
        page = action - 9187000
        authors = getattr(player, '_tl_authors', [])
        if authors:
            xml = _build_trackauthorlist_window(page, authors)
            player._tl_author_page = page
            await _send(aseco, login, xml)
        return

    if -9187249 <= action <= -9187000:
        page = abs(action) - 9187000
        authors = getattr(player, '_tl_authors', [])
        if authors:
            xml = _build_trackauthorlist_window(page, authors)
            player._tl_author_page = page
            await _send(aseco, login, xml)
        return

    # TrackauthorlistWindow selection: -9188000 to -91812999
    if -91812999 <= action <= -9188000:
        idx = abs(action) - 9188000
        authors = getattr(player, '_tl_authors', [])
        if 0 <= idx < len(authors):
            await _send_tracklist_author_filter(aseco, player, idx)
        return

    # ── Default: togglewidgets ──────────────────────────────────────────────
    if action == ACTION_TOGGLE:
        await chat_togglewidgets(aseco, {'author': player, 'params': ''})
