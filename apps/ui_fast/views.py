"""Compact TMF-native panels inspired by Gilles Masson's FAST 3 interface."""

import re

from pyxaseco.helpers import format_time, safe_manialink_text


ML_BAR, ML_MAP, ML_RECORDS, ML_MENU = range(8585000, 8585004)
ML_SPLITS = 8585004
ML_TEAM = 8585005
TOGGLE, SOURCE_PREV, SOURCE_NEXT, OPEN_RECORDS, OPEN_MAP = range(8585100, 8585105)
BACK, CLOSE, MENU_PREV, MENU_NEXT, STYLES = range(8585105, 8585110)
SPLIT_MODE = 8585110
ITEM_BASE = 8585200
PAGE_SIZE = 18
PAGES = re.compile(r'<manialink\b[^>]*(?:/>|>.*?</manialink>)', re.DOTALL)
PAGE_ID = re.compile(r'\bid=["\']([^"\']+)["\']')


def suppress(xml, *, menu=True, track=True, records=True, live_splits=False):
    replaced = set()
    if menu:
        replaced.update(('3830000', '3830001'))
    if track:
        replaced.add('91805')
    if records:
        replaced.update(('91811', '91812'))
    if live_splits:
        replaced.add('91834')

    def replace(match):
        page = PAGE_ID.search(match[0].partition('>')[0])
        if page and page[1] in replaced:
            return f'<manialink id="{page[1]}"></manialink>'
        return match[0]
    return PAGES.sub(replace, xml)


def empty(page):
    return f'<manialink id="{page}"></manialink>'


def label(x, y, width, text, *, color='EEEE', align='left'):
    return (f'<label posn="{x:.4f} {y:.4f} 0.02" sizen="{width:.4f} 1.7"'
            f' textsize="1" textcolor="{color}" halign="{align}"'
            f' text="{safe_manialink_text(str(text))}"/>')


def card(x, y, width, height, action=None):
    return (f'<quad posn="{x:.4f} {y:.4f} 0" sizen="{width:.4f} {height:.4f}"'
            ' style="BgsPlayerCard" substyle="BgCardSystem"'
            + (f' action="{action}"' if action is not None else '') + '/>')


def icon(x, y, style, action):
    return (f'<quad posn="{x:.4f} {y:.4f} 0.03" sizen="1.6 1.6"'
            f' style="Icons64x64_1" substyle="{style}" action="{action}"/>')


def page(identifier, x, y, body):
    return f'<manialink id="{identifier}"><frame posn="{x:.4f} {y:.4f} 5">{body}</frame></manialink>'


def bar(values, mode, players, spectators):
    width = values['menu/width']
    body = card(0, 0, width, 2.2, TOGGLE)
    body += label(.5, -.35, width - 1, f'$oFAST  $z{mode}  {players}P / {spectators}S')
    return page(ML_BAR, values['menu/pos_x'], values['menu/pos_y'], body)


def map_panel(values, track, next_track=None):
    width = values['map/width']
    body = card(0, 0, width, 8.7, OPEN_MAP)
    if next_track:
        body += label(.5, -.3, width - 1, '$aaaNext Track')
        name = next_track.get('name') or '-'
        author = next_track.get('author') or '-'
        environment = next_track.get('env') or ''
        time = next_track.get('authortime') or '-'
    else:
        body += label(.5, -.3, width - 1, '$aaaCurrent Track')
        name = getattr(track, 'name', '-') or '-'
        author = getattr(track, 'author', '-') or '-'
        environment = getattr(track, 'environment', '') or ''
        time = format_time(getattr(track, 'authortime', 0) or 0)
    body += label(.5, -2.4, width - 1, name)
    body += label(.5, -4.4, width - 1, '$bbbby $fff' + str(author))
    body += label(.5, -6.4, width - 1, '$ddd' + str(environment) + '  $fff' + str(time))
    return page(ML_MAP, values['map/pos_x'], values['map/pos_y'], body)


def split_delta(value):
    if value is None:
        return '$aaa--'
    sign = '-' if value < 0 else '+' if value > 0 else ''
    color = '$09f' if value <= 0 else '$f33'
    return color + sign + format_time(abs(value))


def splits(values, model, nickname=''):
    width = values['splits/width']
    time = format_time(model['time']) if model['time'] is not None else '--'
    checkpoint = 'Finish' if model['finished'] else f"CP {model['cp']}/{model['total'] or '?'}"
    if model['lap']:
        checkpoint = f"Lap {model['lap']}  " + checkpoint
    body = label(width / 2, 0, width,
                 f"$fff{checkpoint}  {time}  $bbbPB $z{split_delta(model['personal'])}", align='center')
    body += (f'<label posn="{width / 2:.4f} -2.2 0.02" sizen="{width:.4f} 1.7"'
             ' textsize="1" textcolor="EEEE" halign="center"'
             f' action="{SPLIT_MODE}" text="'
             + safe_manialink_text(f"$bbb{model['title']}  $z{split_delta(model['comparison'])}") + '"/>')
    detail = ('$fff' + nickname + '$z  ') if nickname else ''
    if model['position']:
        rank, total = model['position']
        detail += f'$bbbPosition $fff{rank}/{total}'
    if detail:
        body += label(width / 2, -4.4, width, detail, align='center')
    for index, gap in enumerate(model.get('gaps', ())):
        progress = f" $bbb({gap['progress']:+d} CP)" if gap['progress'] else ''
        delta = split_delta(gap['delta'])
        if gap['delta'] is not None:
            delta += ' $bbb@ ' + gap['checkpoint']
        y = -6.6 - 1.8 * index
        body += label(.5, y, width * .61, f"$bbb{gap['label']} $fff{gap['name']}$z{progress}")
        body += label(width - .5, y, width * .38, delta, align='right')
    return page(ML_SPLITS, values['splits/pos_x'], values['splits/pos_y'], body)


def records(values, source, rows, login, position, total, *, stunts=False):
    width, step = values['records/width'], values['records/row_height']
    body = card(0, 0, width, 2.2 + step * max(1, len(rows)) + 1.8)
    body += label(2.2, -.3, width - 4.6, '$ff0$o' + source.title)
    body += icon(.2, -.1, 'ArrowPrev', SOURCE_PREV)
    body += icon(width - 1.8, -.1, 'ArrowNext', SOURCE_NEXT)
    for index, row in enumerate(rows):
        y = -2.4 - index * step
        if row['login'] == login:
            body += f'<quad posn="0.1 {y + .2:.4f} 0.01" sizen="{width - .2:.4f} {step:.4f}" bgcolor="09F4"/>'
        body += label(.4, y, 2.5, str(row['rank']) + '.', color='FF0F')
        body += label(3.0, y, width - 9.4, row['nickname'])
        score = str(row['score']) if stunts else format_time(row['score'])
        body += label(width - .4, y, 6.0, score, align='right')
    if not rows:
        body += label(.5, -2.4, width - 1, '$aaaNo records yet')
    bottom = -2.2 - step * max(1, len(rows))
    body += card(0, bottom, width, 1.8, OPEN_RECORDS)
    body += label(.5, bottom - .1, width - 1, f'$bbbOpen list  {position + 1}/{total}')
    return page(ML_RECORDS, values['records/pos_x'], values['records/pos_y'], body)


def team_match(values, match, round_=None, login=''):
    width = values['competition/width']
    rows = []
    if match:
        state = 'Save failed - paused' if match.get('error') else match['state']
        if state == 'stopped' and match.get('target_reached'):
            state = 'complete'
        rows.append(('$ff0$oTeam Match $z$bbb' + state, ''))
        for team, color in ((0, '$39f'), (1, '$f55')):
            rows.append((color + match['names'][team], str(match['totals'][team])))
        scoring = 'map wins' if match.get('rules', {}).get('scoring') == 'map_wins' else 'map points'
        rows.append((f'$bbb{match["counted"]} maps counted | {scoring}', ''))
        for row in [row for row in match['maps'] if not row['void']][-values['competition/history_rows']:]:
            rows.append((row['name'], f'{row["scores"][0]} - {row["scores"][1]}'))
    if round_:
        score = round_['points']
        name = 'Round result' if round_['final'] else 'Live round'
        rows.append((f'$ff0{name} {round_["number"]} $z$bbb(est.)',
                     f'$39f{score[0]} $fff- $f55{score[1]}' if score is not None else '--'))
        racers = [racer for racer in round_['players'] if racer['rank'] is not None][:3]
        own = next((racer for racer in round_['players'] if racer['login'] == login), None)
        if own and own not in racers:
            racers.append(own)
        for racer in racers:
            name = 'You' if racer['login'] == login else racer['name']
            color = ('$39f', '$f55')[racer['team']]
            rank = f"#{racer['rank']}" if racer['rank'] is not None else 'DNF'
            points = racer['points']
            rows.append((f'$bbb{rank} {color}{name}', f'{points} pt' if points is not None else '--'))
    body = card(0, 0, width, 2 + 1.8 * len(rows))
    for index, (name, score) in enumerate(rows):
        y = -.3 - 1.8 * index
        body += label(.5, y, width - (9 if score else 1), name)
        if score:
            body += label(width - .5, y, 8, score, align='right')
    return page(ML_TEAM, values['competition/pos_x'], values['competition/pos_y'], body)


def menu(values, title, entries, index, count):
    width = max(25, values['menu/width'])
    body = card(0, 0, width, 5.5 + 2.0 * len(entries))
    body += label(2.2, -.3, width - 4.6, '$ff0$o' + title)
    body += icon(.2, -.1, 'ArrowPrev', BACK)
    body += icon(width - 1.8, -.1, 'Close', CLOSE)
    for row, entry in enumerate(entries):
        y = -2.4 - row * 2.0
        body += card(.2, y + .2, width - .4, 2.0, ITEM_BASE + row)
        body += label(.6, y, width - 1.2, entry.caption + ('  >' if entry.is_group() else ''))
    bottom = -2.6 - 2.0 * len(entries)
    body += icon(.4, bottom, 'ArrowPrev', MENU_PREV)
    body += label(2.5, bottom, 3.5, f'{index + 1}/{count}')
    body += icon(width - 2, bottom, 'ArrowNext', MENU_NEXT)
    # This route stays available even when the owner's FuFi menu is disabled.
    body += card(6.3, bottom + .15, width - 12.6, 1.8, STYLES)
    body += label(6.7, bottom, width - 13.4, '$bbbUI Styles')
    return page(ML_MENU, values['menu/pos_x'], values['menu/pos_y'] - 2.5, body)
