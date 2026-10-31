"""Trial map statistics: exact checkpoint tables and bounded native ManiaLink charts."""

from html import escape
import math

from pyxaseco.helpers import ML_ID_MAIN, _player_window_style, _s, _send_multipage, format_time


ROWS_PER_PAGE = 14
CHECKPOINTS_PER_CHART = 24
TABLE_WIDTHS = [1.55, .12, .14, .30, .30, .40, .29]
ICON = ['Icons64x64_1', 'TrackInfo']
CHARTS = (
    ('Segment times', (('avg_segment_time_ms', 'Average', 'accent'),
                       ('median_segment_time_ms', 'Median', 'top')), True),
    ('Cumulative times', (('avg_checkpoint_time_ms', 'Average elapsed', 'accent'),), True),
    ('Respawns', (('avg_respawns_segment', 'Average respawns', 'accent'),), False),
)
PERSONAL_CHARTS = (
    ('Your segment times', (('segment_time_ms', 'Your PB', 'accent'),), True),
    ('Your cumulative times', (('checkpoint_time_ms', 'Your PB elapsed', 'accent'),), True),
    ('Your respawns', (('respawns_segment', 'Your PB respawns', 'accent'),), False),
)


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def checkpoint_stats(payload, known_uids):
    if payload is None:
        return []
    if not isinstance(payload, dict) or payload.get('ok') is not True or not isinstance(payload.get('stats'), list):
        raise ValueError('Invalid Trial checkpoint response')
    track = payload.get('track') or {}
    if not isinstance(track, dict):
        raise ValueError('Invalid Trial checkpoint track')
    identities = {str(value) for value in (
        payload.get('challenge_uid'), track.get('challenge_uid'), track.get('storage_uid'), track.get('uid_primary')) if value}
    if not identities.intersection(known_uids):
        raise ValueError('Trial checkpoint track identity mismatch')
    result, seen = [], set()
    for row in payload['stats']:
        if not isinstance(row, dict):
            raise ValueError('Invalid Trial checkpoint row')
        uid = str(row.get('challenge_uid') or '')
        if uid and uid not in known_uids:
            raise ValueError('Trial checkpoint row identity mismatch')
        index = _number(row.get('checkpoint_index'))
        if index is None or not index.is_integer() or index < 1 or index in seen:
            raise ValueError('Invalid or duplicate Trial checkpoint index')
        seen.add(index)
        item = {'checkpoint_index': int(index)}
        for field in ('sample_count', 'avg_segment_time_ms', 'median_segment_time_ms',
                      'avg_checkpoint_time_ms', 'avg_respawns_segment'):
            item[field] = _number(row.get(field))
        result.append(item)
    return sorted(result, key=lambda row: row['checkpoint_index'])


def personal_record(records, login):
    matches = []
    for position, row in enumerate(records, 1):
        names = [row.get('login'), row.get('player_login'), row.get('primary_login'), row.get('best_login')]
        family = row.get('family_logins')
        if isinstance(family, list):
            names.extend(family)
        if str(login).casefold() not in {str(value).casefold() for value in names if value}:
            continue
        score = _number(row.get('best_score') or row.get('score'))
        if score is None or score <= 0 or not score.is_integer():
            continue
        best_login = str(row.get('best_login') or row.get('player_login') or row.get('login') or login)
        matches.append({'best_score': int(score), 'best_login': best_login,
                        'rank': row.get('rank') or row.get('rank_no') or position,
                        'nickname': row.get('player_nickname') or row.get('nickname') or best_login})
    return min(matches, key=lambda row: row['best_score']) if matches else None


def personal_splits(payload, known_uids, record):
    if payload is None:
        return [], None, False
    if not isinstance(payload, dict) or payload.get('ok') is not True or not isinstance(payload.get('runs'), list):
        raise ValueError('Invalid Trial personal checkpoint response')
    if str(payload.get('challenge_uid') or '') not in known_uids:
        raise ValueError('Trial personal checkpoint track mismatch')
    groups = {}
    for row in payload['runs']:
        if not isinstance(row, dict):
            raise ValueError('Invalid Trial personal checkpoint row')
        if str(row.get('challenge_uid') or '') not in known_uids:
            raise ValueError('Trial personal checkpoint row track mismatch')
        if str(row.get('login') or row.get('player_login') or '').casefold() != record['best_login'].casefold():
            raise ValueError('Trial personal checkpoint login mismatch')
        if _number(row.get('finish_time_ms')) != record['best_score']:
            continue
        # Do not build an artificial PB from different sources/replays or ambiguous ties.
        key = (str(row.get('source') or ''), str(row.get('source_uid') or ''), str(row.get('tmx_replay_id') or ''))
        groups.setdefault(key, []).append(row)
    candidates = []
    for key, run in groups.items():
        by_index, ambiguous = {}, False
        for row in run:
            index = _number(row.get('checkpoint_index'))
            elapsed = _number(row.get('checkpoint_time_ms'))
            if index is None or index < 1 or not index.is_integer() or elapsed is None or elapsed <= 0:
                ambiguous = True
                break
            item = {'checkpoint_index': int(index), 'checkpoint_time_ms': elapsed,
                    'respawns_segment': _number(row.get('respawns_segment'))}
            if index in by_index and by_index[index] != item:
                ambiguous = True
                break
            by_index[index] = item
        ordered = [by_index[index] for index in sorted(by_index)]
        if ambiguous or not ordered or ordered[-1]['checkpoint_time_ms'] != record['best_score']:
            continue
        previous = 0
        for index, item in enumerate(ordered, 1):
            if item['checkpoint_index'] != index or item['checkpoint_time_ms'] < previous:
                ambiguous = True
                break
            item['segment_time_ms'] = item['checkpoint_time_ms'] - previous
            item['label'] = 'Fin' if index == len(ordered) else f'CP{index}'
            previous = item['checkpoint_time_ms']
        if not ambiguous:
            candidates.append((ordered, {'source': key[0]}))
    limited = len(payload['runs']) >= int(payload.get('limit') or 5000)
    if not candidates:
        return [], None, limited
    selected, source = max(candidates, key=lambda candidate: len(candidate[0]))
    return selected, source, limited


def _checkpoint(row):
    # Match the website's public checkpoint-table/chart numbering.
    return row.get('label') or f"CP{row['checkpoint_index'] - 1}"


def _time(value):
    return '--' if value is None else format_time(round(value))


def _decimal(value):
    return '--' if value is None else f'{value:.2f}'.rstrip('0').rstrip('.')


def pages(info_rows, stats, unavailable=False, *, personal=False):
    rows = list(info_rows)
    if stats:
        if personal:
            summary = f'{len(stats)} entries from one complete run matching your PB.'
        else:
            samples = max((row['sample_count'] or 0 for row in stats), default=0)
            summary = f'{len(stats)} entries; up to {int(samples)} samples per entry'
        rows.append(['$zCheckpoint data', '{#black}' + summary])
    else:
        if unavailable:
            message = f"Checkpoint API unavailable; reopen /{'trialpb' if personal else 'trialinfo'} to retry."
        else:
            message = 'No complete checkpoint run matching your PB is available.' if personal else 'No checkpoint statistics available for this map.'
        rows.append(['$zCheckpoint data', '{#black}' + message])
    output = [{'title': 'Personal best' if personal else 'Map information', 'widths': [1.2, .3, .9], 'rows': rows[i:i + ROWS_PER_PAGE]}
              for i in range(0, len(rows), ROWS_PER_PAGE)]
    if not stats:
        return output
    # A fixed scale across chunks makes different chart pages comparable.
    for title, series, timed in PERSONAL_CHARTS if personal else CHARTS:
        values = [row[key] for row in stats for key, _label, _color in series if row[key] is not None]
        if not values:
            continue
        maximum = max(values)
        for offset in range(0, len(stats), CHECKPOINTS_PER_CHART):
            caption = 'Your saved PB run, not live splits' if personal else 'Website samples, not live splits'
            output.append({'title': title, 'widths': [1.55], 'rows': [[]] * ROWS_PER_PAGE,
                           'chart': (stats[offset:offset + CHECKPOINTS_PER_CHART], series, timed, maximum, caption)})
    if personal:
        headings = ['$zCP', '$zElapsed', '$zSegment', '$zRespawns']
        table = [[_checkpoint(row), _time(row['checkpoint_time_ms']), _time(row['segment_time_ms']),
                  _decimal(row['respawns_segment'])] for row in stats]
        widths = [1.2, .15, .4, .4, .25]
    else:
        headings = ['$zCP', '$zSamples', '$zAvg segment', '$zMedian', '$zAvg elapsed', '$zRespawns']
        table = [[_checkpoint(row), '--' if row['sample_count'] is None else str(int(row['sample_count'])), _time(row['avg_segment_time_ms']),
                  _time(row['median_segment_time_ms']), _time(row['avg_checkpoint_time_ms']),
                  _decimal(row['avg_respawns_segment'])] for row in stats]
        widths = TABLE_WIDTHS
    for offset in range(0, len(table), ROWS_PER_PAGE - 1):
        output.append({'title': 'Your checkpoint times' if personal else 'Checkpoint times (averages)', 'widths': widths,
                       'rows': [headings] + table[offset:offset + ROWS_PER_PAGE - 1]})
    return output


async def show(aseco, player, title, info_rows, stats, valid_page, *, unavailable=False, personal=False):
    content = pages(info_rows, stats, unavailable, personal=personal)

    def prepare(controller, viewer):
        if not valid_page(controller, viewer):
            return False
        index = viewer.msgs[0][0] - 1
        if not 0 <= index < len(content):
            return False
        selected = content[index]
        viewer.msgs[0][1:3] = [title + ' $z| ' + selected['title'], selected['widths']]
        return True

    def render(viewer, header, rows, widths, page, total):
        selected = content[page - 1]
        if 'chart' not in selected:
            return None
        return chart_xml(aseco, viewer, header, page, total, *selected['chart'])

    player.msgs = [[1, title, [1.2, .3, .9], ICON, prepare, None, None, render]]
    player.msgs.extend(item['rows'] for item in content)
    await _send_multipage(aseco, player)


def chart_xml(aseco, player, header, page, total, rows, series, timed, maximum,
              caption='Website samples, not live splits'):
    lookup = getattr(aseco, 'get_service', None)
    styles = lookup('ui/uistyle') if callable(lookup) else None
    preset = styles.resolve(player) if styles is not None else None
    colors = {'background': '222B', 'header': '345C', 'text': 'FFFF',
              'muted': 'BBBF', 'accent': '3CFF', 'top': 'FD8F'}
    if preset is not None and preset.base == 1:
        colors.update(preset.palette or {})
    classic = _player_window_style(aseco, player)
    modern = preset is not None and preset.base == 1 and preset.window is None
    window_width, window_height = 90, 53
    parts = [f'<manialink id="{ML_ID_MAIN}"><frame posn="{-window_width / 2} {window_height / 2} 20">']

    def quad(x, y, width, height, color, z=.03):
        parts.append(f'<quad posn="{x:.4f} {y:.4f} {z:.4f}" sizen="{width:.4f} {height:.4f}" bgcolor="{escape(color, quote=True)}"/>')

    def label(x, y, width, text, color=None, align='left', scale=.75):
        text = str(text).replace('{#black}', '$' + colors['text'][:3])
        parts.append(f'<label posn="{x:.4f} {y:.4f} 0.06" sizen="{width:.4f} 2" textsize="1" scale="{scale}"'
                     f' halign="{align}" textcolor="{color or colors["text"]}" text="{escape(text, quote=True)}"/>')

    def skin(role, x, y, width, height, color, z=.01):
        name, substyle = _s(classic, role + '.STYLE'), _s(classic, role + '.SUBSTYLE')
        if not modern and name and substyle:
            parts.append(f'<quad posn="{x} {y} {z}" sizen="{width} {height}"'
                         f' style="{escape(name, quote=True)}" substyle="{escape(substyle, quote=True)}"/>')
        else:
            quad(x, y, width, height, color, z=z)

    skin('WINDOW', 0, 0, window_width, window_height, colors['background'])
    skin('HEADER', .8, -1.3, window_width - 1.6, 3, colors['header'], z=.02)
    if not modern:
        skin('BODY', .8, -4.5, window_width - 1.6, window_height - 9.5, colors['background'], z=.02)
    if modern:
        quad(0, 0, .3, window_height, colors['accent'])
    parts.append('<quad posn="1.8 -1 0.04" sizen="3.2 3.2" style="Icons64x64_1" substyle="TrackInfo"/>')
    label(5.5, -1.9, window_width - 22, header, scale=1)
    label(window_width - 2, -1.9, 12, f'{page} / {total}', colors['muted'], 'right', 1)
    label(3, -6, window_width - 8, f'{_checkpoint(rows[0])} - {_checkpoint(rows[-1])} | {caption} | -- = missing')
    for index, (_key, caption, color) in enumerate(series):
        quad(10 + index * 40, -10, 1.2, 1.2, colors[color])
        label(12 + index * 40, -9.8, 37, '$z' + caption)

    plot_x, plot_width, plot_top, plot_height = 9, window_width - 13, -14, window_height - 30
    plot_bottom = plot_top - plot_height
    scale_max = maximum if maximum > 0 else 1
    for fraction in (0, .25, .5, .75, 1):
        y = plot_top - plot_height + fraction * plot_height
        quad(plot_x, y, plot_width, .05, colors['muted'][:3] + '5')
        value = maximum * fraction
        tick = _time(value) if timed else _decimal(value)
        label(plot_x - .6, y + .6, 7.5, tick, colors['muted'], 'right', .65)
    quad(plot_x, plot_top, .08, plot_height, colors['muted'])
    step = plot_width / max(1, len(rows))
    bar_width = min(3, step * .72 / len(series)) * .5
    for index, row in enumerate(rows):
        center = plot_x + step * (index + .5)
        for offset, (key, _caption, color) in enumerate(series):
            value = row[key]
            x = center + (offset - len(series) / 2) * bar_width
            if value is None:
                label(x + bar_width / 2, plot_bottom + 1.3, bar_width, '--', colors['muted'], 'center', .5)
                continue
            height = plot_height * value / scale_max
            quad(x, plot_bottom + max(.08, height), bar_width * .88, max(.08, height), colors[color], z=.04)
        label(center, plot_bottom - 1.2, step, _checkpoint(row), colors['text'], 'center', .6)
    label(3, -(window_height - 10), window_width - 6, '$zExact values are on the checkpoint-table pages.', colors['muted'])

    def nav(x, icon, action):
        parts.append(f'<quad posn="{x} {-(window_height - 3.9):.4f} 0.06" sizen="2.8 2.8" halign="center"'
                     f' style="Icons64x64_1" substyle="{icon}" action="{action}"/>')

    if page > 1:
        nav(3.3, 'ArrowFirst', -4)
        nav(window_width * .25, 'ArrowPrev', -2)
        if total > 5:
            nav(7, 'ArrowFastPrev', -3)
    nav(window_width / 2, 'Close', 0)
    if page < total:
        nav(window_width * .75, 'ArrowNext', 2)
        nav(window_width - 3.3, 'ArrowLast', 4)
        if total > 5:
            nav(window_width - 7, 'ArrowFastNext', 3)
    parts.append('</frame></manialink>')
    return ''.join(parts)
