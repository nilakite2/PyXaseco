"""Server-local FAST match reports; never publish player data automatically."""

from html import escape
import os
from uuid import uuid4

from pyxaseco.helpers import format_time, strip_colors


def plain(text):
    return ' '.join(strip_colors(str(text)).split())


def report_text(match):
    blue, red = map(plain, match['names'])
    rules = match.get('rules', {})
    lines = [
        'PyXaseco FAST Team Match', f"Match: {match['match_id']} ({match['state']})",
        f"{blue} {match['totals'][0]} - {match['totals'][1]} {red}",
        f"Scoring: {rules.get('scoring', 'native')} | Target: {rules.get('target', 0) or 'manual stop'}"
        f" | Win margin: {rules.get('win_margin', 1)}", '',
        'Map scores are native results. Individual round points are estimates.', '',
    ]
    for index, row in enumerate(match['maps'], 1):
        lines.append(f"{index}. {plain(row['name'])} [{plain(row['uid'])}]"
                     f" | {row['scores'][0]} - {row['scores'][1]}"
                     + (' (void)' if row['void'] else ''))
        for round_ in row.get('rounds', ()):
            points = round_['points']
            score = f'{points[0]} - {points[1]}' if points is not None else 'unavailable'
            lines.append(f"   Round {round_['number']} | estimated {score}")
            for racer in round_['players']:
                name, login = plain(racer['name']), plain(racer['login'])
                rank = racer['rank'] if racer['rank'] is not None else 'DNF'
                time = format_time(racer['time_ms']) if racer['time_ms'] else '--'
                points = racer['points'] if racer['points'] is not None else '--'
                checkpoint = f" at CP {racer['checkpoint']}" if racer['checkpoint'] is not None else ''
                lines.append(f"      {rank} | {('Blue', 'Red')[racer['team']]} | "
                             f"{name} ({login}) | {time}{checkpoint} | {points} pts")
        if row.get('rounds_omitted', 0):
            lines.append(f"   {row['rounds_omitted']} further rounds not retained.")
    if match['adjustments']:
        lines.extend(('', 'Administrative adjustments:'))
        for item in match['adjustments']:
            lines.append(f"   {plain(item.get('at', ''))} {plain(item['action'])}"
                         f" by {plain(item.get('actor', ''))}")
    return '\n'.join(lines) + '\n'


def write_report(folder, match, kind):
    if kind not in ('txt', 'html'):
        raise ValueError('Export format must be txt or html.')
    from pyxaseco.management.installation import safe_path
    folder = safe_path(folder)
    folder.mkdir(parents=True, mode=0o700, exist_ok=True)
    path = folder / f"fast-match-{uuid4().hex[:12]}.{kind}"
    text = report_text(match)
    if kind == 'html':
        text = ('<!doctype html>\n<html lang="en"><meta charset="utf-8">'
                '<title>FAST Team Match</title><h1>FAST Team Match</h1>'
                '<pre>' + escape(text) + '</pre></html>\n')
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        os.chmod(path, 0o600)
        stream.write(text)
    return path.name
