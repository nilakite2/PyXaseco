"""Optional rotating, fully clickable sponsor image widget."""

from dataclasses import dataclass
from html import escape
import logging
from math import isfinite
from pathlib import Path, PurePosixPath
from time import monotonic
from urllib.parse import quote, unquote, urlsplit

from pyxaseco.app_config import (
    AppSetting, AppSettingsSchema, as_bool, as_float, as_int, as_str,
    bind_app_settings, clear_app_defaults_cache,
)
from pyxaseco.core.base import App
from pyxaseco.core.file_io import file_io
from pyxaseco.core.widget_delivery import deliver_ui, is_score_phase


logger = logging.getLogger(__name__)
ML_ID = 5834292
MAX_SPONSORS = 100
SCHEMA = AppSettingsSchema(app_id='sponsor_banner', settings=(
    AppSetting('enabled', True, as_bool, 'Enable the sponsor banner.'),
    AppSetting('interval_seconds', 30, as_int, 'Default rotation interval, 1-86400 seconds.'),
    AppSetting('show_in_race', True, as_bool, 'Show while racing.'),
    AppSetting('show_on_score', True, as_bool, 'Show during the score screen.'),
    AppSetting('pos_x', -7.88, as_float, 'Banner X position; initially top-centre.'),
    AppSetting('pos_y', 47.5, as_float, 'Banner Y position.'),
    AppSetting('width', 15.76, as_float, 'Banner width; ManiaKarma size by default.'),
    AppSetting('height', 10.75, as_float, 'Banner height; ManiaKarma size by default.'),
    AppSetting('local_directory', 'images', as_str, 'Local image folder; relative to this app or absolute.'),
    AppSetting('asset_base_url', '', as_str, 'Public HTTP(S) address serving local_directory, not a file:// path.'),
))
APP_METADATA = {
    'id': 'sponsor_banner', 'display_name': 'Sponsor Banner',
    'description': 'Rotating clickable sponsor images with per-player widget visibility.',
    'modules': ['apps/sponsor_banner/app.py'], 'entries': ['app/sponsor_banner'],
    'provides': ['feature/sponsor_banner'], 'depends_on': ['platform_core', 'ui'],
}


@dataclass(frozen=True)
class Banner:
    key: str
    image_url: str
    link_url: str
    duration: int
    order: int


def web_url(value, *, clickable=False):
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError('Supply a non-empty image/link URL of at most 4096 characters.')
    if any(ord(char) <= 32 or ord(char) == 127 for char in value) or '\\' in value:
        raise ValueError('Image/link URLs must not contain whitespace, control characters or backslashes.')
    if clickable and '://' not in value:
        value = 'http://' + value
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError('Invalid image/link URL.') from error
    if (parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or (port is not None and not 1 <= port <= 65535)):
        raise ValueError('Use an HTTP(S) image/link URL without embedded credentials.')
    # TMF's external-browser links use HTTP; the browser can follow HTTPS redirects.
    if clickable and parsed.scheme.lower() == 'https':
        value = 'http' + value[value.index(':'):]
    return value


def _integer(value, minimum, maximum, label):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{label} must be an integer from {minimum} to {maximum}.')
    return value


def _local_image(name, values, root):
    if not isinstance(name, str):
        raise ValueError('image_file must be a filename relative to local_directory.')
    relative = name.replace('\\', '/')
    if (not relative or len(relative) > 1024 or relative.startswith('/') or ':' in relative
            or any(part in ('', '.', '..') for part in relative.split('/'))
            or any(ord(char) < 32 or ord(char) == 127 for char in relative)):
        raise ValueError('image_file must stay inside local_directory; absolute paths and traversal are not allowed.')
    if not values['local_directory']:
        raise ValueError('Set local_directory for image_file entries.')
    directory = Path(values['local_directory'])
    if not directory.is_absolute():
        directory = root / 'apps' / 'sponsor_banner' / directory
    directory = directory.resolve()
    target = (directory / Path(*PurePosixPath(relative).parts)).resolve()
    if not target.is_relative_to(directory) or not target.is_file():
        raise ValueError('Local sponsor image is missing or outside local_directory.')
    base = web_url(values['asset_base_url'])
    parsed = urlsplit(base)
    if parsed.query or parsed.fragment:
        raise ValueError('asset_base_url must be a public directory URL without query or fragment.')
    return base.rstrip('/') + '/' + quote(relative, safe='/')


def configuration(section, root):
    if not isinstance(section, dict):
        raise ValueError('sponsor_banner must be a TOML table.')
    values = {setting.key: setting.read(section) for setting in SCHEMA.settings}
    for key in ('pos_x', 'pos_y', 'width', 'height'):
        if not isfinite(values[key]):
            raise ValueError('Banner position and size must be finite numbers.')
    if not 0 < values['width'] <= 128 or not 0 < values['height'] <= 96:
        raise ValueError('Banner width must be 0-128 and height 0-96, both greater than zero.')
    if not -64.7 <= values['pos_x'] <= 64.7 or not -48 <= values['pos_y'] <= 48:
        raise ValueError('Banner position must be within X -64.7 to 64.7 and Y -48 to 48.')
    _integer(values['interval_seconds'], 1, 86400, 'interval_seconds')
    if values['asset_base_url']:
        web_url(values['asset_base_url'])
    entries = section.get('sponsors', {})
    if not isinstance(entries, dict) or len(entries) > MAX_SPONSORS:
        raise ValueError(f'sponsors must be a table containing at most {MAX_SPONSORS} entries.')
    banners = []
    for position, (key, entry) in enumerate(entries.items(), 1):
        if not isinstance(entry, dict):
            raise ValueError('Each sponsor needs its own TOML table.')
        enabled = entry.get('enabled', True)
        if type(enabled) is not bool:
            raise ValueError(f'Sponsor {key}: enabled must be true or false.')
        if not enabled:
            continue
        try:
            image, local = entry.get('image_url', ''), entry.get('image_file', '')
            if bool(image) == bool(local):
                raise ValueError('Set exactly one of image_url or image_file.')
            image = web_url(image) if image else _local_image(local, values, Path(root))
            path = unquote(urlsplit(image).path).lower()
            if not path.endswith(('.jpg', '.jpeg', '.png', '.tga', '.dds', '.gif')):
                raise ValueError('Use a direct JPG, PNG, TGA, DDS or GIF image address.')
            link = web_url(entry.get('link_url', ''), clickable=True)
            duration = _integer(entry.get('duration_seconds', 0), 0, 86400, 'duration_seconds')
            order = _integer(entry.get('order', position), 0, 100000, 'order')
            banners.append(Banner(str(key), image, link, duration or values['interval_seconds'], order))
        except ValueError as error:
            raise ValueError(f'Sponsor {key}: {error}') from error
    return values, tuple(sorted(banners, key=lambda banner: banner.order))


def validate_config(document, root):
    configuration(document.get('sponsor_banner', {}), root)


class SponsorBannerApp(App):
    def __init__(self):
        super().__init__(app_id='sponsor_banner', display_name='Sponsor Banner',
            description=APP_METADATA['description'], depends_on=('platform_core', 'ui'),
            entry_modules=('app/sponsor_banner',), settings_schema=SCHEMA)
        self.enabled = False
        self.values, self.banners = {}, ()
        self.index, self.next_at = 0, None
        self.hidden = set()

    def register_runtime(self, aseco):
        for event, callback in (
            ('onEverySecond', self.tick), ('onSync', self.refresh),
            ('onPlayerConnect2', self.connect), ('onPlayerDisconnect', self.disconnect),
            ('onWidgetVisibilityChanged', self.visibility),
            ('onNewChallenge', self.refresh), ('onRestartChallenge', self.refresh),
            ('onEndRace', self.refresh), ('onStatusChangeTo3', self.refresh),
            ('onStatusChangeTo5', self.refresh),
        ):
            aseco.register_event(event, callback)

    async def configure(self, aseco):
        bound = await file_io(bind_app_settings, SCHEMA, getattr(aseco, '_base_dir', None))
        values, banners = await file_io(configuration, bound.section, Path(aseco._base_dir))
        # Validate the complete candidate before replacing the running rotation.
        self.values, self.banners, self.enabled = values, banners, values['enabled']
        self.index = 0
        self.next_at = monotonic() + banners[0].duration if banners else None

    async def startup(self, context):
        try:
            await self.configure(context.aseco)
        except (OSError, ValueError) as error:
            logger.warning('[SponsorBanner] Configuration invalid; banner hidden: %s', error)
            self.enabled = False
        await self.refresh(context.aseco)

    async def shutdown(self, context):
        self.enabled = False
        await self.refresh(context.aseco)
        self.hidden.clear()

    def showing(self, aseco):
        if not self.enabled or not self.banners:
            return False
        return self.values['show_on_score'] if is_score_phase(aseco) else self.values['show_in_race']

    def eligible(self, player):
        from apps.ui.config import _state
        return player.login not in self.hidden and _state.player_visible.get(player.login, True)

    def xml(self):
        banner = self.banners[self.index]
        return (f'<manialink id="{ML_ID}"><frame posn="{self.values["pos_x"]:.4f} '
                f'{self.values["pos_y"]:.4f} 1">'
                f'<quad posn="0 0 0" sizen="{self.values["width"]:.4f} {self.values["height"]:.4f}"'
                f' image="{escape(banner.image_url, quote=True)}"'
                f' url="{escape(banner.link_url, quote=True)}"/></frame></manialink>')

    async def draw(self, aseco, player):
        xml = self.xml() if self.showing(aseco) and self.eligible(player) else f'<manialink id="{ML_ID}"></manialink>'
        await deliver_ui(aseco, 'SendDisplayManialinkPageToLogin', player.login, xml, 0, False)

    async def refresh(self, aseco, _data=None):
        showing = self.showing(aseco)
        shown, hidden = [], []
        for player in aseco.server.players.all():
            (shown if showing and self.eligible(player) else hidden).append(player.login)
        for recipients, xml in ((shown, self.xml() if showing else ''),
                                (hidden, f'<manialink id="{ML_ID}"></manialink>')):
            for start in range(0, len(recipients), 100):
                await deliver_ui(aseco, 'SendDisplayManialinkPageToLogin',
                                 ','.join(recipients[start:start + 100]), xml, 0, False)

    async def tick(self, aseco, _data=None):
        if not self.enabled or not self.banners or self.next_at is None or monotonic() < self.next_at:
            return
        self.index = (self.index + 1) % len(self.banners)
        self.next_at = monotonic() + self.banners[self.index].duration
        if len(self.banners) > 1:
            await self.refresh(aseco)

    async def connect(self, aseco, player):
        self.hidden.discard(player.login)
        await self.draw(aseco, player)

    async def disconnect(self, _aseco, player):
        self.hidden.discard(player.login)

    async def visibility(self, aseco, data):
        player = aseco.server.players.get_player(data['login'])
        if player is None:
            return
        if data['visible']:
            self.hidden.discard(player.login)
        else:
            self.hidden.add(player.login)
        await self.draw(aseco, player)


APP_CLASS = SponsorBannerApp
APP_INSTANCE = SponsorBannerApp()


def register(aseco):
    APP_INSTANCE.register_runtime(aseco)


async def reload_runtime(aseco):
    clear_app_defaults_cache(aseco._base_dir)
    await APP_INSTANCE.configure(aseco)
    await APP_INSTANCE.refresh(aseco)
