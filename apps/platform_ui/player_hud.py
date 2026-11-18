"""In-game editor for per-style HUD overrides. No startup directory scan."""

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
import logging
import xml.etree.ElementTree as ET

from pyxaseco.core.file_io import file_io
from pyxaseco.core.widget_delivery import deliver_ui, is_score_phase
from pyxaseco.helpers import safe_manialink_text

from . import hud_layout as layout
from . import hud_transfer
from . import panels


logger = logging.getLogger(__name__)
EDITOR = '8542000'
PANEL_PREVIEW = '8542001'
BASE = 8542100
SAVE, CANCEL, RESET_PANEL, HIDE, LEFT, RIGHT, UP, DOWN, SMALLER, LARGER, PREV, NEXT = range(BASE, BASE + 12)
DENSITY_STANDARD, DENSITY_COMPACT, DENSITY_MINIMAL = range(BASE + 12, BASE + 15)
TEMPLATE_PREV, TEMPLATE_NEXT, TEMPLATE_DEFAULT = range(BASE + 15, BASE + 18)
EXPORT, IMPORT_HELP = range(BASE + 18, BASE + 20)
SELECT = BASE + 20
STEP_SELECT = BASE + 100
PAGE_SIZE = 7
MOVEMENT = {LEFT: ('dx', -1), RIGHT: ('dx', 1), UP: ('dy', 1), DOWN: ('dy', -1)}


@dataclass
class Session:
    player: object
    styles: dict = field(default_factory=dict)
    ready: bool = False
    writable: bool = True
    saving: bool = False
    transferring: bool = False
    task: object = None
    preset: str | None = None
    draft: dict = field(default_factory=dict)
    selected: str = ''
    page: int = 0
    density: str = 'standard'
    draft_density: str = 'standard'
    templates: dict = field(default_factory=dict)
    preview: str = ''
    step: float = 1


def editor_xml(title, available, session, *, preset=None, style=None, compact=layout.COMPACT_DEFAULT,
               legacy_off=(), template_choices=None, template='', transfer=False):
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
    move_space = 3 if available.get(panel) else 0
    extra = move_space + (6.7 if template_choices else 0)
    window_height = 32 + extra + (3.2 if transfer else 0)
    values = layout.effective(panel, session.draft_density, session.draft.get(panel, {}), compact)
    background = (f' bgcolor="{palette["background"]}"' if palette
                  else skin('WINDOW', ('Bgs1InRace', 'BgWindow1')))
    header = (f' bgcolor="{palette["header"]}"' if palette
              else skin('HEADER', ('Bgs1InRace', 'BgTitle2')))
    xml = [
        f'<manialink id="{EDITOR}"><frame posn="-21.5 18 23">',
        f'<quad posn="0 0 0" sizen="43 {window_height:g}"{background}/>',
        f'<quad posn="0 0 0.01" sizen="43 2.8"{header}/>',
        label(.8, -.45, 41, '$fff$oHUD layout $z' + title, heading=True),
    ]
    if palette:
        xml.append(f'<quad posn="0 0 0.015" sizen=".14 {window_height:g}" bgcolor="{palette["accent"]}"/>')
    if not rows:
        xml.append(label(.8, -4, 41, 'No supported panels are visible in this race.'))
    for index, name in enumerate(rows[first:first + PAGE_SIZE]):
        title = layout.PANELS[name][0]
        hidden = name in legacy_off or layout.effective(
            name, session.draft_density, session.draft.get(name, {}), compact).get('hidden')
        xml.append(button(.7, -3.3 - index * 2.55, 20,
                          ('$ff0> ' if name == panel else '') + title + (' $aaa(off)' if hidden else ''),
                          SELECT + list(layout.PANELS).index(name)))
    if first:
        xml.append(button(.7, -21.3, 8, 'Prev', PREV))
    if first + PAGE_SIZE < len(rows):
        xml.append(button(9, -21.3, 8, 'Next', NEXT))
    if panel in available:
        xml.extend((label(22, -3.4, 20, layout.PANELS[panel][0]),
                    button(22, -6, 18, 'Show' if values.get('hidden') or panel in legacy_off else 'Hide', HIDE)))
        if available[panel]:
            dx, dy, scale = (values.get(key, layout.DEFAULTS[key]) for key in ('dx', 'dy', 'scale'))
            xml.append(label(22, -9.3, 20, f'Offset X {dx:+g} | Y {dy:+g} | {scale:.0%}'))
            xml.append(label(22, -12.35, 4.6, 'Step'))
            for i, step in enumerate(layout.POSITION_STEPS):
                caption = ('$ff0' if session.step == step else '') + f'{step:g}'
                xml.append(button(27 + i * 4.8, -12, 4.5, caption, STEP_SELECT + i))
            for x, y, text, action in ((22, -15, 'Left', LEFT), (32, -15, 'Right', RIGHT),
                                       (22, -18, 'Up', UP), (32, -18, 'Down', DOWN),
                                       (22, -21, 'Smaller', SMALLER), (32, -21, 'Larger', LARGER)):
                xml.append(button(x, y, 9, text, action))
        else:
            xml.append(label(22, -10, 20, '$aaaVisibility only'))
        xml.append(button(22, -21.3 - move_space, 18,
                          'Reset layout' if template_choices else 'Reset panel', RESET_PANEL))
        if template_choices:
            xml.extend((label(22, -24.2 - move_space, 20,
                              'Template: ' + (template_choices.get(template, template) or 'Off')),
                        button(22, -26.8 - move_space, 4, '<', TEMPLATE_PREV),
                        button(27, -26.8 - move_space, 4, '>', TEMPLATE_NEXT)))
            if 'default' in template_choices:
                xml.append(button(32, -26.8 - move_space, 10, 'Use default', TEMPLATE_DEFAULT))
    for index, density in enumerate(layout.DENSITIES):
        caption = ('$ff0> ' if density == session.draft_density else '') + density.capitalize()
        xml.append(button(.7 + index * 14, -24.3 - extra, 13, caption, DENSITY_STANDARD + index))
    xml.extend((button(.7, -28 - extra, 12, 'Save', SAVE), button(14, -28 - extra, 12, 'Cancel', CANCEL),
                label(28, -28.3 - extra, 14, '$aaaLive preview')))
    if transfer:
        xml.extend((button(.7, -31.1 - extra, 12, 'Export saved', EXPORT),
                    button(14, -31.1 - extra, 12, 'Import help', IMPORT_HELP)))
    xml.append('</frame></manialink>')
    return ''.join(xml)


class PlayerHud:
    def __init__(self, styles):
        self.styles = styles
        self.aseco = styles.aseco
        self.sessions = {}
        self.compact = layout.COMPACT_DEFAULT
        self.server_offsets = {}

    def register(self):
        for event, handler in (
            ('onPlayerConnect', self.connect), ('onPlayerDisconnect', self.disconnect),
            ('onShutdown', self.shutdown), ('onChat_hud', self.command),
            ('onPlayerManialinkPageAnswer', self.answer), ('onUiStyleChanged', self.style_changed),
            ('onWidgetVisibilityChanged', self.visibility), ('onEndRace', self.transition),
            ('onNewChallenge', self.transition), ('onRestartChallenge', self.transition),
        ):
            self.aseco.register_event(event, handler)
        self.aseco.add_chat_command('hud', 'Customize, share or reset your race HUD',
                                    app='platform_ui', owner='ui/hud', usage='/hud [reset|export|restore <code>]')

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
            saved, density = await file_io(layout.read_profile, path, with_density=True)
        except (OSError, ValueError):
            session.writable = False
            saved, density = {}, 'standard'
            logger.warning('[HUD] Cannot read layout for %s; preserving the file and using defaults', player.login)
        if self.session(player) is not session or not self.styles.connected(player):
            return
        session.styles = saved
        session.density = density
        session.ready = True
        try:
            await self.refresh(player, layout.PANELS if density != 'standard' else saved.get(self.preset(player), ()))
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

    def _preferences(self, player, preset):
        session = self.session(player)
        if session is None or not session.ready:
            return {}, 'standard'
        selected = str(preset.id)
        editing = session.preset == selected
        return ((session.draft, session.draft_density) if editing
                else (session.styles.get(selected, {}), session.density))

    def transform(self, player, preset, xml):
        overrides, density = self._preferences(player, preset)
        session = self.session(player)
        if session and session.preset == str(preset.id) and session.preview and session.preview != 'vote_panel':
            key = session.preview
            if any(f'id="{page}"' in xml or f"id='{page}'" in xml for page in layout.PANELS[key][1]):
                # Keep the real source cached while the selected panel is shown as an inert preview.
                overrides = {**overrides, key: {'hidden': True}}
        return self.render_layout(xml, overrides, density)

    def render_layout(self, xml, overrides, density):
        return layout.transform(xml, overrides, density, compact=self.compact, server_offsets=self.server_offsets)

    def saved_panel_xml(self, player, xml):
        preset = self.preset(player)
        session = self.session(player)
        if session is None or not session.ready:
            return self.render_layout(xml, {}, 'standard')
        return self.render_layout(xml, session.styles.get(preset, {}), session.density)

    def panel_geometry(self, player, identifier, x, y):
        overrides, density = self._preferences(player, self.styles.resolve(player))
        return layout.panel_geometry(identifier, x, y, overrides.get(layout.BY_PAGE.get(identifier), {}),
                                     density, self.compact)

    def available(self, player):
        presentation = self.styles.presentation
        active = {}
        legacy = panels.hud_panels(self.aseco, player)
        for (login, identifier), fragment in presentation.sources.items():
            key = layout.BY_PAGE.get(identifier)
            if (not key or key in panels.HUD_PANEL_TYPES or login != player.login
                    or (login, identifier) not in presentation.race_sources):
                continue
            fragment = self.styles.transform_xml(player, fragment)
            node, geometry = layout.inspect(fragment, visibility_only=key in layout.VISIBILITY_ONLY)
            if node is not None:
                active[key] = active.get(key, True) and geometry
        session = self.session(player)
        for key in legacy:
            choice = session.templates.get(key) if session else None
            if choice is None and not panels.hud_panel_enabled(player, key):
                choice = next(iter(panels.hud_choices(self.aseco, key)), None)
            xml = panels.hud_template_xml(self.aseco, player, key, choice)
            if xml:
                active[key] = layout.inspect(xml)[1]
        return {key: active[key] for key in layout.PANELS if key in active}

    async def refresh(self, player, names):
        if names and not is_score_phase(self.aseco) and self.styles.connected(player):
            pages = {page for name in names for page in layout.PANELS[name][1]}
            await self.styles.presentation.refresh(player, pages=pages)

    async def send(self, player, xml):
        if self.styles.connected(player):
            await deliver_ui(self.aseco, 'SendDisplayManialinkPageToLogin', player.login, xml, 0, False)

    async def clear_vote_preview(self, player):
        session = self.session(player)
        if session and session.preview == 'vote_panel':
            session.preview = ''
            await self.send(player, f'<manialink id="{PANEL_PREVIEW}"></manialink>')

    async def sync_preview(self, player, session, available, preset):
        key = session.selected
        fragment = ''
        if key in available and key in panels.HUD_PANEL_TYPES:
            source = self.styles.presentation.sources.get((player.login, layout.PANELS[key][1][0]))
            if key == 'stats_panel' and source and layout.inspect(source)[0] is not None:
                fragment = source
            else:
                fragment = panels.hud_preview(self.aseco, player, key, session.templates.get(key))
        previous, session.preview = session.preview, key if fragment else ''
        if previous != session.preview:
            await self.refresh(player, {previous, session.preview} - {'', 'vote_panel'})
        if not (fragment or previous):
            return
        fragment = fragment or f'<manialink id="{PANEL_PREVIEW}"></manialink>'
        fragment = self.aseco.format_colors(fragment)
        fragment = self.styles.transform_xml(player, fragment)
        fragment = self.render_layout(fragment, session.draft, session.draft_density)
        try:
            page = ET.fromstring(fragment)
        except ET.ParseError:
            page = ET.Element('manialink')
        if page.tag != 'manialink':
            page = ET.Element('manialink')
        page.attrib.clear()
        page.set('id', PANEL_PREVIEW)
        for node in page.iter():
            for attr in ('action', 'actionkey', 'url', 'manialink', 'scriptevents'):
                node.attrib.pop(attr, None)
            for child in list(node):
                if child.tag not in ('frame', 'format', 'label', 'quad'):
                    node.remove(child)
        await self.send(player, ET.tostring(page, encoding='unicode'))

    async def draw(self, player, session):
        available = self.available(player)
        session.page = min(session.page, max(0, (len(available) - 1) // PAGE_SIZE))
        if session.selected not in available:
            session.selected = next(iter(available), '')
        preset = self.styles.resolve(player)
        await self.sync_preview(player, session, available, preset)
        key = session.selected
        choices = panels.hud_choices(self.aseco, key) if key in panels.HUD_PANEL_TYPES else {}
        template = (session.templates.get(key, panels.hud_selected_template(player, key)) if choices else '')
        legacy_off = {key for key in available if key in panels.HUD_PANEL_TYPES and key not in session.templates
                      and not panels.hud_panel_enabled(player, key)}
        style = self.styles.window_style(player, getattr(player, 'style', None) or {})
        await self.send(player, editor_xml(preset.name, available, session,
                                          preset=preset, style=style, compact=self.compact,
                                          legacy_off=legacy_off, template_choices=choices, template=template,
                                          transfer=hud_transfer.available()))

    async def close(self, session, *, redraw=False):
        if session.preset is None:
            return
        previous = set(session.draft) | set(session.styles.get(session.preset, {}))
        preview = session.preview
        if preview and preview != 'vote_panel':
            previous.add(preview)
        if session.draft_density != session.density:
            previous = layout.PANELS
        session.preset = None
        session.draft = {}
        session.templates.clear()
        session.preview = ''
        session.selected = ''
        session.page = 0
        await self.send(session.player, f'<manialink id="{EDITOR}"></manialink>')
        if preview:
            await self.send(session.player, f'<manialink id="{PANEL_PREVIEW}"></manialink>')
        if redraw:
            await self.refresh(session.player, previous)

    async def save(self, player, session, preset, values, density):
        styles = deepcopy(session.styles)
        if values:
            styles[preset] = values
        else:
            styles.pop(preset, None)
        if styles == session.styles and density == session.density:
            return True
        session.saving = True
        try:
            saved = await file_io(layout.write_profile, layout.profile_path(self.styles.root, player.login), styles, density)
        except (OSError, ValueError):
            logger.warning('[HUD] Cannot save layout for %s', player.login, exc_info=True)
            await self.styles.reply(player, '{#error}HUD layout was not saved. Your saved settings are unchanged.')
            return False
        finally:
            session.saving = False
        if self.session(player) is not session:
            return False
        session.styles = saved
        session.density = density
        return True

    async def apply_transfer(self, player, session, preset, document):
        if not session.writable or session.saving or self.session(player) is not session:
            return
        if await self.save(player, session, preset, document['panels'], document['density']):
            await self.close(session)
            await self.refresh(player, layout.PANELS)
            target = self.styles.resolve(player).name
            await self.styles.reply(player, f'HUD layout restored to {target}. The shared HUD density was updated too.')

    async def command(self, _aseco, command):
        player = command['author']
        session = self.session(player)
        args = str(command.get('params') or '').strip().lower()
        verb, _, rest = args.partition(' ')
        if session is None or not session.ready or session.saving or session.transferring:
            await self.styles.reply(player, 'Your HUD layout is busy. Try again in a moment.')
        elif not session.writable:
            await self.styles.reply(player, '{#error}Your HUD file could not be read. Defaults are active; ask an admin to check it.')
        elif args == 'export':
            preset = self.styles.resolve(player)
            document = {'version': 1, 'style': preset.name, 'density': session.density,
                        'panels': session.styles.get(str(preset.id), {})}
            await hud_transfer.request(self, player, session, 'export', document)
        elif verb in ('import', 'restore'):
            code = rest.strip()
            if not hud_transfer.CODE.fullmatch(code):
                await self.styles.reply(player, 'Use /hud restore <20-digit code>.')
            else:
                await hud_transfer.request(self, player, session, 'restore', code)
        elif args == 'reset':
            preset = self.preset(player)
            changed = (set(session.styles.get(preset, {})) | set(session.draft) | {session.preview}) - {''}
            if session.density != 'standard' or session.draft_density != 'standard':
                changed = layout.PANELS
            if await self.save(player, session, preset, {}, 'standard'):
                await self.close(session)
                await self.refresh(player, changed)
                await self.styles.reply(player, 'HUD reset to server defaults for ' + self.styles.resolve(player).name + '.')
        elif args:
            await self.styles.reply(player, 'Use /hud, /hud reset, /hud export, or /hud restore <code>.')
        elif is_score_phase(self.aseco):
            await self.styles.reply(player, 'Open /hud during the race to preview your panels.')
        else:
            preset = self.preset(player)
            if session.preset != preset:
                session.preset = preset
                session.draft = deepcopy(session.styles.get(preset, {}))
                session.draft_density = session.density
            await self.draw(player, session)

    async def answer(self, _aseco, answer):
        if len(answer) < 3:
            return
        try:
            action = int(answer[2])
        except (ValueError, TypeError):
            return
        step_choice = STEP_SELECT <= action < STEP_SELECT + len(layout.POSITION_STEPS)
        if not (BASE <= action < SELECT + len(layout.PANELS) or step_choice):
            return
        player = self.aseco.server.players.get_player(answer[1])
        session = self.session(player) if player else None
        if (not session or session.saving or session.transferring or session.preset != self.preset(player)
                or is_score_phase(self.aseco)):
            return
        if action == CANCEL:
            await self.close(session, redraw=True)
            return
        if action == EXPORT:
            await self.command(self.aseco, {'author': player, 'params': 'export'})
            return
        if action == IMPORT_HELP:
            await self.styles.reply(player, 'Use /hud restore <20-digit code> to replace the saved layout for this preset.')
            return
        if action == SAVE:
            preset = session.preset
            changed = (set(session.styles.get(preset, {})) | set(session.draft) | {session.preview}) - {''}
            templates = dict(session.templates)
            if await self.save(player, session, preset, session.draft, session.draft_density):
                session.saving = True
                try:
                    saved_templates = await panels.save_hud_choices(self.aseco, player, templates)
                finally:
                    session.saving = False
                if self.session(player) is not session:
                    return
                if not saved_templates:
                    await self.styles.reply(player, '{#error}HUD layout saved, but panel templates could not be saved.')
                    return
                await self.close(session)
                await self.refresh(player, changed - templates.keys())
                await panels.redraw_hud_choices(self.aseco, player, templates)
                await self.styles.reply(player, 'HUD layout saved for ' + self.styles.resolve(player).name + '.')
            return
        if DENSITY_STANDARD <= action <= DENSITY_MINIMAL:
            session.draft_density = layout.DENSITIES[action - DENSITY_STANDARD]
            await self.refresh(player, layout.PANELS)
            await self.draw(player, session)
            return
        available = self.available(player)
        panel = session.selected
        if step_choice:
            if not available.get(panel):
                return
            session.step = layout.POSITION_STEPS[action - STEP_SELECT]
        elif action >= SELECT:
            selected = list(layout.PANELS)[action - SELECT]
            if selected in list(available)[session.page * PAGE_SIZE:(session.page + 1) * PAGE_SIZE]:
                session.selected = selected
        elif action in (PREV, NEXT):
            session.page = max(0, session.page + (-1 if action == PREV else 1))
        elif panel in available:
            values = dict(session.draft.get(panel, {}))
            defaults = layout.DEFAULTS | layout.defaults(panel, session.draft_density, self.compact)
            if action == RESET_PANEL:
                values.clear()
            elif panel in panels.HUD_PANEL_TYPES and (
                    action in (TEMPLATE_PREV, TEMPLATE_NEXT, TEMPLATE_DEFAULT) or
                    action == HIDE and panel not in session.templates and not panels.hud_panel_enabled(player, panel)):
                choices = list(panels.hud_choices(self.aseco, panel))
                current = session.templates.get(panel, panels.hud_selected_template(player, panel))
                if not choices or (action == TEMPLATE_DEFAULT and 'default' not in choices):
                    return
                if action in (HIDE, TEMPLATE_DEFAULT):
                    choice = choices[0]
                else:
                    step = -1 if action == TEMPLATE_PREV else 1
                    index = choices.index(current) + step if current in choices else (-1 if step < 0 else 0)
                    choice = choices[index % len(choices)]
                session.templates[panel] = choice
                key = 'hidden'
                values[key] = False
            elif action == HIDE:
                values['hidden'] = not values.get('hidden', defaults['hidden'])
            elif available[panel] and (action in MOVEMENT or action in (SMALLER, LARGER)):
                if action in MOVEMENT:
                    key, sign = MOVEMENT[action]
                    step = session.step * sign
                else:
                    key, step = 'scale', -.1 if action == SMALLER else .1
                low, high = layout.LIMITS[key]
                values[key] = round(max(low, min(high, values.get(key, defaults[key]) + step)), 2)
            else:
                return
            if action == HIDE:
                key = 'hidden'
            if action != RESET_PANEL and values.get(key) == defaults[key]:
                values.pop(key, None)
            if values:
                session.draft[panel] = values
            else:
                session.draft.pop(panel, None)
            if panel != 'vote_panel' and panel != session.preview:
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
