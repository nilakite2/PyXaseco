"""In-game editor for per-style HUD overrides. No startup directory scan."""

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
import logging

from pyxaseco.core.file_io import file_io
from pyxaseco.core.widget_delivery import deliver_ui, is_score_phase
from pyxaseco.helpers import safe_manialink_text

from . import hud_layout as layout


logger = logging.getLogger(__name__)
EDITOR = '8542000'
BASE = 8542100
SAVE, CANCEL, RESET_PANEL, HIDE, LEFT, RIGHT, UP, DOWN, SMALLER, LARGER, PREV, NEXT = range(BASE, BASE + 12)
SELECT = BASE + 20
PAGE_SIZE = 7


@dataclass
class Session:
    player: object
    styles: dict = field(default_factory=dict)
    ready: bool = False
    writable: bool = True
    saving: bool = False
    task: object = None
    preset: str | None = None
    draft: dict = field(default_factory=dict)
    selected: str = ''
    page: int = 0


def editor_xml(title, available, session, *, preset=None, style=None):
    palette = preset.palette if preset is not None and preset.base == 1 else None

    def skin(section, fallback):
        block = (style or {}).get(section, [{}])[0]
        name = block.get('STYLE', [fallback[0]])[0]
        substyle = block.get('SUBSTYLE', [fallback[1]])[0]
        return (f' style="{safe_manialink_text(name)}"'
                f' substyle="{safe_manialink_text(substyle)}"')

    def label(x, y, width, text, action=None, *, heading=False):
        click = f' action="{action}"' if action is not None else ''
        # Native title skins override compact label sizing and action colors.
        color = palette['text'] if palette else 'FFFF'
        scale = 1 if heading else .9
        appearance = f' textcolor="{color}" scale="{scale}" autonewline="0"'
        return (f'<label posn="{x} {y} 0.02" sizen="{width} 2.1" textsize="1"'
                f'{appearance}{click} text="{safe_manialink_text(text)}"/>')

    def button(x, y, width, text, action):
        appearance = (f' bgcolor="{palette["selection"]}"' if palette
                      else skin('BUTTON', ('Bgs1InRace', 'NavButton')))
        return (f'<quad posn="{x} {y} 0.01" sizen="{width} 2.5"'
                f'{appearance} action="{action}"/>' + label(x + .5, y - .35, width - 1, text, action))

    rows = list(available)
    first = session.page * PAGE_SIZE
    panel = session.selected
    values = session.draft.get(panel, {})
    background = (f' bgcolor="{palette["background"]}"' if palette
                  else skin('WINDOW', ('Bgs1InRace', 'BgWindow1')))
    header = (f' bgcolor="{palette["header"]}"' if palette
              else skin('HEADER', ('Bgs1InRace', 'BgTitle2')))
    xml = [
        f'<manialink id="{EDITOR}"><frame posn="-61 22 23">',
        f'<quad posn="0 0 0" sizen="43 29"{background}/>',
        f'<quad posn="0 0 0.01" sizen="43 2.8"{header}/>',
        label(.8, -.45, 41, '$fff$oHUD layout $z' + title, heading=True),
    ]
    if palette:
        xml.append(f'<quad posn="0 0 0.015" sizen=".14 29" bgcolor="{palette["accent"]}"/>')
    if not rows:
        xml.append(label(.8, -4, 41, 'No supported panels are visible in this race.'))
    for index, name in enumerate(rows[first:first + PAGE_SIZE]):
        title = layout.PANELS[name][0]
        hidden = session.draft.get(name, {}).get('hidden')
        xml.append(button(.7, -3.3 - index * 2.55, 20,
                          ('$ff0> ' if name == panel else '') + title + (' $aaa(off)' if hidden else ''),
                          SELECT + list(layout.PANELS).index(name)))
    if first:
        xml.append(button(.7, -21.3, 8, 'Prev', PREV))
    if first + PAGE_SIZE < len(rows):
        xml.append(button(9, -21.3, 8, 'Next', NEXT))
    if panel in available:
        xml.extend((label(22, -3.4, 20, layout.PANELS[panel][0]),
                    button(22, -6, 18, 'Show' if values.get('hidden') else 'Hide', HIDE)))
        if available[panel]:
            dx, dy, scale = (values.get(key, layout.DEFAULTS[key]) for key in ('dx', 'dy', 'scale'))
            xml.append(label(22, -9.3, 20, f'X {dx:+g} | Y {dy:+g} | {scale:.0%}'))
            for x, y, text, action in ((22, -12, 'Left', LEFT), (32, -12, 'Right', RIGHT),
                                       (22, -15, 'Up', UP), (32, -15, 'Down', DOWN),
                                       (22, -18, 'Smaller', SMALLER), (32, -18, 'Larger', LARGER)):
                xml.append(button(x, y, 9, text, action))
        else:
            xml.append(label(22, -10, 20, '$aaaVisibility only'))
        xml.append(button(22, -21.3, 18, 'Reset panel', RESET_PANEL))
    xml.extend((button(.7, -25, 12, 'Save', SAVE), button(14, -25, 12, 'Cancel', CANCEL),
                label(28, -25.3, 14, '$aaaLive preview'), '</frame></manialink>'))
    return ''.join(xml)


class PlayerHud:
    def __init__(self, styles):
        self.styles = styles
        self.aseco = styles.aseco
        self.sessions = {}

    def register(self):
        for event, handler in (
            ('onPlayerConnect', self.connect), ('onPlayerDisconnect', self.disconnect),
            ('onShutdown', self.shutdown), ('onChat_hud', self.command),
            ('onPlayerManialinkPageAnswer', self.answer), ('onUiStyleChanged', self.style_changed),
            ('onWidgetVisibilityChanged', self.visibility), ('onEndRace', self.transition),
            ('onNewChallenge', self.transition), ('onRestartChallenge', self.transition),
        ):
            self.aseco.register_event(event, handler)
        self.aseco.add_chat_command('hud', 'Customize your race HUD or restore the default layout',
                                    app='platform_ui', owner='ui/hud', usage='/hud [reset]')

    def preset(self, player):
        return str(self.styles.resolve(player).id)

    def session(self, player):
        session = self.sessions.get(player.login)
        return session if session and session.player is player else None

    async def connect(self, _aseco, player):
        old = self.sessions.pop(player.login, None)
        if old and old.task and not old.task.done():
            old.task.cancel()
        session = Session(player)
        self.sessions[player.login] = session
        session.task = asyncio.create_task(self.load(session))

    async def load(self, session):
        player = session.player
        path = layout.profile_path(self.styles.root, player.login)
        try:
            saved = await file_io(layout.read_profile, path)
        except (OSError, ValueError):
            session.writable = False
            saved = {}
            logger.warning('[HUD] Cannot read layout for %s; preserving the file and using defaults', player.login)
        if self.session(player) is not session or not self.styles.connected(player):
            return
        session.styles = saved
        session.ready = True
        try:
            await self.refresh(player, saved.get(self.preset(player), ()))
        except Exception:
            logger.warning('[HUD] Could not refresh the loaded layout for %s', player.login, exc_info=True)

    async def disconnect(self, _aseco, player):
        session = self.session(player)
        if session is not None:
            self.sessions.pop(player.login, None)
            if session.task and not session.task.done():
                session.task.cancel()

    async def shutdown(self, _aseco, _data=None):
        tasks = [session.task for session in self.sessions.values() if session.task and not session.task.done()]
        self.sessions.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def transform(self, player, preset, xml):
        session = self.session(player)
        if session is None or not session.ready:
            return xml
        selected = str(preset.id)
        overrides = session.draft if session.preset == selected else session.styles.get(selected)
        return layout.transform(xml, overrides)

    def available(self, player):
        presentation = self.styles.presentation
        active = {}
        for (login, identifier), fragment in presentation.sources.items():
            key = layout.BY_PAGE.get(identifier)
            if not key or login != player.login or (login, identifier) not in presentation.race_sources:
                continue
            fragment = self.styles.transform_xml(player, fragment)
            node, geometry = layout.inspect(fragment, visibility_only=key in layout.VISIBILITY_ONLY)
            if node is not None:
                active[key] = active.get(key, True) and geometry
        return {key: active[key] for key in layout.PANELS if key in active}

    async def refresh(self, player, names):
        if names and not is_score_phase(self.aseco) and self.styles.connected(player):
            pages = {page for name in names for page in layout.PANELS[name][1]}
            await self.styles.presentation.refresh(player, pages=pages)

    async def send(self, player, xml):
        if self.styles.connected(player):
            await deliver_ui(self.aseco, 'SendDisplayManialinkPageToLogin', player.login, xml, 0, False)

    async def draw(self, player, session):
        available = self.available(player)
        session.page = min(session.page, max(0, (len(available) - 1) // PAGE_SIZE))
        if session.selected not in available:
            session.selected = next(iter(available), '')
        preset = self.styles.resolve(player)
        style = self.styles.window_style(player, getattr(player, 'style', None) or {})
        await self.send(player, editor_xml(preset.name, available, session, preset=preset, style=style))

    async def close(self, session, *, redraw=False):
        if session.preset is None:
            return
        previous = set(session.draft) | set(session.styles.get(session.preset, {}))
        session.preset = None
        session.draft = {}
        session.selected = ''
        session.page = 0
        await self.send(session.player, f'<manialink id="{EDITOR}"></manialink>')
        if redraw:
            await self.refresh(session.player, previous)

    async def save(self, player, session, preset, values):
        styles = deepcopy(session.styles)
        if values:
            styles[preset] = values
        else:
            styles.pop(preset, None)
        if styles == session.styles:
            return True
        session.saving = True
        try:
            saved = await file_io(layout.write_profile, layout.profile_path(self.styles.root, player.login), styles)
        except (OSError, ValueError):
            logger.warning('[HUD] Cannot save layout for %s', player.login, exc_info=True)
            await self.styles.reply(player, '{#error}HUD layout was not saved. Your saved settings are unchanged.')
            return False
        finally:
            session.saving = False
        if self.session(player) is not session:
            return False
        session.styles = saved
        return True

    async def command(self, _aseco, command):
        player = command['author']
        session = self.session(player)
        args = str(command.get('params') or '').strip().lower()
        if session is None or not session.ready or session.saving:
            await self.styles.reply(player, 'Your HUD layout is loading or saving. Try again in a moment.')
        elif not session.writable:
            await self.styles.reply(player, '{#error}Your HUD file could not be read. Defaults are active; ask an admin to check it.')
        elif args == 'reset':
            preset = self.preset(player)
            changed = set(session.styles.get(preset, {})) | set(session.draft)
            if await self.save(player, session, preset, {}):
                await self.close(session)
                await self.refresh(player, changed)
                await self.styles.reply(player, 'HUD reset to server defaults for ' + self.styles.resolve(player).name + '.')
        elif args:
            await self.styles.reply(player, 'Use /hud to edit your layout or /hud reset to restore this style.')
        elif is_score_phase(self.aseco):
            await self.styles.reply(player, 'Open /hud during the race to preview your panels.')
        else:
            preset = self.preset(player)
            if session.preset != preset:
                session.preset = preset
                session.draft = deepcopy(session.styles.get(preset, {}))
            await self.draw(player, session)

    async def answer(self, _aseco, answer):
        if len(answer) < 3:
            return
        try:
            action = int(answer[2])
        except (ValueError, TypeError):
            return
        if not BASE <= action < SELECT + len(layout.PANELS):
            return
        player = self.aseco.server.players.get_player(answer[1])
        session = self.session(player) if player else None
        if (not session or session.saving or session.preset != self.preset(player)
                or is_score_phase(self.aseco)):
            return
        if action == CANCEL:
            await self.close(session, redraw=True)
            return
        if action == SAVE:
            preset = session.preset
            changed = set(session.styles.get(preset, {})) | set(session.draft)
            if await self.save(player, session, preset, session.draft):
                await self.close(session)
                await self.refresh(player, changed)
                await self.styles.reply(player, 'HUD layout saved for ' + self.styles.resolve(player).name + '.')
            return
        available = self.available(player)
        panel = session.selected
        if action >= SELECT:
            selected = list(layout.PANELS)[action - SELECT]
            if selected in list(available)[session.page * PAGE_SIZE:(session.page + 1) * PAGE_SIZE]:
                session.selected = selected
        elif action in (PREV, NEXT):
            session.page = max(0, session.page + (-1 if action == PREV else 1))
        elif panel in available:
            values = dict(session.draft.get(panel, {}))
            if action == RESET_PANEL:
                values.clear()
            elif action == HIDE:
                values['hidden'] = not values.get('hidden', False)
            elif available[panel] and action in (LEFT, RIGHT, UP, DOWN, SMALLER, LARGER):
                key, step = {LEFT: ('dx', -2), RIGHT: ('dx', 2), UP: ('dy', 2), DOWN: ('dy', -2),
                             SMALLER: ('scale', -.1), LARGER: ('scale', .1)}[action]
                low, high = layout.LIMITS[key]
                values[key] = round(max(low, min(high, values.get(key, layout.DEFAULTS[key]) + step)), 2)
            else:
                return
            values = {key: value for key, value in values.items() if value != layout.DEFAULTS[key]}
            if values:
                session.draft[panel] = values
            else:
                session.draft.pop(panel, None)
            await self.refresh(player, (panel,))
        await self.draw(player, session)

    async def style_changed(self, _aseco, data):
        session = self.sessions.get(data.get('login'))
        if session and session.preset is not None and session.preset != self.preset(session.player):
            await self.close(session)

    async def visibility(self, _aseco, data):
        session = self.sessions.get(data.get('login'))
        if session and not data.get('visible'):
            await self.close(session, redraw=True)

    async def transition(self, _aseco, _data=None):
        for session in list(self.sessions.values()):
            await self.close(session)
