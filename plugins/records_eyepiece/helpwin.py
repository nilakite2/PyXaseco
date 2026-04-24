from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

from .ui import append_window_start, append_window_end


ML_WINDOW = 91800
ML_SUBWIN = 91801


def _build_help_window(aseco: 'Aseco', page: int = 0) -> str:
    """
    Port of re_buildHelpWindow() — 3 pages of command help.
    Action IDs for pagination: 91816x.
    """

    def page_btns(cur_p: int) -> str:
        b = '<frame posn="67.05 -53.2 0">'
        if cur_p > 0:
            b += (
                f'<quad posn="4.95 0 0.12" sizen="3.2 3.2" '
                f'action="-{918160 + cur_p - 1}" '
                f'style="Icons64x64_1" substyle="ArrowPrev"/>'
            )
        else:
            b += (
                '<quad posn="4.95 0 0.12" sizen="3.2 3.2" '
                'style="Icons64x64_1" substyle="StarGold"/>'
            )

        if cur_p < 2:
            b += (
                f'<quad posn="8.25 0 0.12" sizen="3.2 3.2" '
                f'action="{918160 + cur_p + 1}" '
                f'style="Icons64x64_1" substyle="ArrowNext"/>'
            )
        else:
            b += (
                '<quad posn="8.25 0 0.12" sizen="3.2 3.2" '
                'style="Icons64x64_1" substyle="StarGold"/>'
            )
        b += '</frame>'
        return b


    p = []
    append_window_start(
        p,
        ml_window=ML_WINDOW,
        ml_subwin=ML_SUBWIN,
        title='Records-Eyepiece Help',
        icon_style='BgRaceScore2',
        icon_substyle='LadderRank',
        content_frame_pos='3 -6 0.01',
    )
    p.append(page_btns(page))

    # Page 0: Player commands
    if page == 0:
        cmds = [
            ('/eyepiece',               'Display this help window'),
            ('/eyepiece hide',          'Hide the record widgets (stored in session)'),
            ('/eyepiece show',          'Show the record widgets (stored in session)'),
            ('/togglewidgets  or  F7',  'Toggle display of all record widgets'),
            ('/estat dedirecs',         'Show Dedimania records window'),
            ('/estat localrecs',        'Show local records window'),
            ('/estat topranks',         'Top-ranked players'),
            ('/estat topwinners',       'Players with most wins'),
            ('/estat mostrecords',      'Players holding most local records'),
            ('/estat topplaytime',      'Players with most playtime'),
            ('/estat mostfinished',     'Players who finished the most tracks'),
            ('/elist',                  'Track list window (with filters and sorting)'),
        ]
        for i, (cmd, desc) in enumerate(cmds):
            y = i * -2.0
            p.append(f'<label posn="0 {y} 0.01" sizen="17 2" textsize="1" textcolor="FFFF" text="{cmd}"/>')
            p.append(f'<label posn="18 {y} 0.01" sizen="37.5 2" textsize="1" textcolor="FF0F" text="{desc}"/>')

    # Page 1: /elist filter options
    elif page == 1:
        p.append('<label posn="0 0 0.01" sizen="55 2" textsize="1" textcolor="FFFF" text="/elist [parameter] — filter options:"/>')
        filters = [
            ('jukebox',     'Show only jukeboxed tracks'),
            ('norecent',    'Exclude recently played tracks'),
            ('onlyrecent',  'Show only recently played tracks'),
            ('norank',      'Show only tracks you have no rank on'),
            ('onlyrank',    'Show only tracks you have a rank on'),
            ('nofinish',    'Show only unfinished tracks'),
            ('best',        'Sort by your best rank'),
            ('worst',       'Sort by your worst rank'),
            ('shortest',    'Sort from shortest to longest'),
            ('longest',     'Sort from longest to shortest'),
            ('newest',      'Newest tracks first'),
            ('oldest',      'Oldest tracks first'),
            ('track',       'Sort alphabetically by track name'),
            ('sortauthor',  'Sort alphabetically by author'),
            ('bestkarma',   'Highest karma first'),
            ('worstkarma',  'Lowest karma first'),
            ('<keyword>',   'Search by track name or author'),
        ]
        for i, (cmd, desc) in enumerate(filters):
            y = (i + 1) * -2.0
            p.append(f'<label posn="0 {y} 0.01" sizen="17 2" textsize="1" textcolor="FFFF" text="{cmd}"/>')
            p.append(f'<label posn="18 {y} 0.01" sizen="37.5 2" textsize="1" textcolor="FF0F" text="{desc}"/>')

    # Page 2: Admin commands (/eyeset)
    else:
        p.append('<label posn="0 0 0.01" sizen="55 2" textsize="1" textcolor="FFFF" text="/eyeset — MasterAdmin commands:"/>')
        admin_cmds = [
            ('reload',                   'Reload records_eyepiece.xml config file'),
            ('lfresh <seconds>',         'Set live-refresh interval'),
            ('playermarker true|false',  'Toggle online-player markers in widgets'),
        ]
        for i, (cmd, desc) in enumerate(admin_cmds):
            y = (i + 1) * -2.0
            p.append(f'<label posn="0 {y} 0.01" sizen="17 2" textsize="1" textcolor="FFFF" text="{cmd}"/>')
            p.append(f'<label posn="18 {y} 0.01" sizen="37.5 2" textsize="1" textcolor="FF0F" text="{desc}"/>')

    append_window_end(p)
    return ''.join(p)