"""Small, dependency-free SVG export for external websites, not ManiaLink images."""

from datetime import datetime
from html import escape
import os
from pathlib import Path
import tempfile


def output_path(root, filename):
    root = Path(root).resolve()
    path = (root / filename).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() != '.svg':
        raise ValueError('Graph output must be an .svg file inside the controller folder.')
    return path


def render(data, title, width, height):
    width, height = max(320, min(1920, width)), max(160, min(1080, height))
    since, until = datetime.fromisoformat(data['since']), datetime.fromisoformat(data['at'])
    duration = max(1, (until - since).total_seconds())
    history = data['history']
    maximum = max([1] + [float(row[key] or 0) for row in history for key in ('Players', 'Spectators')])
    left, top, right, bottom = 44, 46, width - 18, height - 34
    items = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             f'<title>{escape(title)} - sampled server population (UTC)</title>',
             '<rect width="100%" height="100%" rx="8" fill="#f4f8fc"/>',
             '<g font-family="Verdana,sans-serif" font-size="11" fill="#294157">',
             f'<text x="{left}" y="23" font-size="14">{escape(title)}</text>',
             f'<text x="{right}" y="23" text-anchor="end">Players / spectators</text>']
    for step in range(5):
        y = bottom - step * (bottom - top) / 4
        items.extend([f'<path d="M {left} {y:.2f} H {right}" stroke="#d6e1ec" fill="none"/>',
                      f'<text x="{left - 7}" y="{y + 4:.2f}" text-anchor="end">{maximum * step / 4:g}</text>'])
    for key, color in (('Players', '#087bc1'), ('Spectators', '#269566')):
        path, previous = [], None
        for row in history:
            at = row['At'] if isinstance(row['At'], datetime) else datetime.fromisoformat(str(row['At']))
            x = left + max(0, min(1, (at - since).total_seconds() / duration)) * (right - left)
            y = bottom - float(row[key] or 0) / maximum * (bottom - top)
            move = previous is None or (at - previous).total_seconds() > data['bucket_seconds'] * 2
            path.append(f'{"M" if move else "L"} {x:.2f} {y:.2f}')
            items.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="1.5" fill="{color}"/>')
            previous = at
        items.append(f'<path d="{" ".join(path)}" fill="none" stroke="{color}" stroke-width="2"/>')
    items.extend([f'<text x="{left}" y="{height - 12}">{since:%m-%d %H:%M} UTC</text>',
                  f'<text x="{right}" y="{height - 12}" text-anchor="end">{until:%m-%d %H:%M} UTC</text>',
                  '</g></svg>'])
    return ''.join(items)


def write(root, filename, data, title, width, height):
    target = output_path(root, filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent, suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(render(data, title, width, height))
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
