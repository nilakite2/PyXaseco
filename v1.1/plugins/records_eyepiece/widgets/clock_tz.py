"""
Clock timezone selection window for Records-Eyepiece.

Action ID scheme (ManialinkId = '918'):
  91803                     -> open the worldmap/group picker window
  918300 to 918319          -> select a region group (group_id = action - 918300)
  918350 to 918799          -> select a specific timezone (tz_id = action - 918350)

Storage: players_extra.Timezone column, format "Display Name|Zone/Name"
If the column doesn't exist it is created on first use.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco

logger = logging.getLogger(__name__)

ML_WINDOW = 91800
ML_SUBWIN = 91801

ACT_CLOCK_OPEN  = 91803
ACT_GROUP_BASE  = 918300   # 918300 + group_index → show that group's TZ list
ACT_TZ_BASE     = 918350   # 918350 + flat_tz_index → select that timezone

WORLDMAP_URL = 'http://maniacdn.net/undef.de/xaseco1/records-eyepiece/worldmap-pure.png'

# ---------------------------------------------------------------------------
# Timezone database
# ---------------------------------------------------------------------------
TIMEZONES: dict[str, list[tuple[str, str]]] = {
    'Africa': [
        ('Algeria / Algiers', 'Africa/Algiers'), ('Angola / Luanda', 'Africa/Luanda'),
        ('Benin / Porto-Novo', 'Africa/Porto-Novo'), ('Bissau-Guinea / Bissau', 'Africa/Bissau'),
        ('Botsuana / Gaborone', 'Africa/Gaborone'), ('Burkina Faso / Ouagadougou', 'Africa/Ouagadougou'),
        ('Burundi / Bujumbura', 'Africa/Bujumbura'), ('Central African Republic / Bangui', 'Africa/Bangui'),
        ('Chad / Ndjamena', 'Africa/Ndjamena'), ('Congo / Brazzaville', 'Africa/Brazzaville'),
        ('Congo / Kinshasa', 'Africa/Kinshasa'), ("Côte d'Ivoire / Abidjan", 'Africa/Abidjan'),
        ('Djibouti / Djibouti', 'Africa/Djibouti'), ('Egypt / Cairo', 'Africa/Cairo'),
        ('Equatorial Guinea / Malabo', 'Africa/Malabo'), ('Eritrea / Asmara', 'Africa/Asmara'),
        ('Ethiopia / Addis Ababa', 'Africa/Addis_Ababa'), ('Gabun / Libreville', 'Africa/Libreville'),
        ('Gambia / Banjul', 'Africa/Banjul'), ('Ghana / Accra', 'Africa/Accra'),
        ('Guinea / Conakry', 'Africa/Conakry'), ('Kamerun / Douala', 'Africa/Douala'),
        ('Kenia / Nairobi', 'Africa/Nairobi'), ('Lesotho / Maseru', 'Africa/Maseru'),
        ('Liberia / Monrovia', 'Africa/Monrovia'), ('Libya / Tripoli', 'Africa/Tripoli'),
        ('Malawi / Blantyre', 'Africa/Blantyre'), ('Mali / Bamako', 'Africa/Bamako'),
        ('Marokko / Casablanca', 'Africa/Casablanca'), ('Mauritania / Nouakchott', 'Africa/Nouakchott'),
        ('Mosambik / Maputo', 'Africa/Maputo'), ('Namibia / Windhoek', 'Africa/Windhoek'),
        ('Niger / Niamey', 'Africa/Niamey'), ('Nigeria / Lagos', 'Africa/Lagos'),
        ('Rwanda / Kigali', 'Africa/Kigali'), ('Sambia / Lusaka', 'Africa/Lusaka'),
        ('Senegal / Dakar', 'Africa/Dakar'), ('Sierra Leone / Freetown', 'Africa/Freetown'),
        ('Simbabwe / Harare', 'Africa/Harare'), ('Somalia / Mogadishu', 'Africa/Mogadishu'),
        ('South Africa / Johannesburg', 'Africa/Johannesburg'), ('Sudan / Khartoum', 'Africa/Khartoum'),
        ('Tanzania / Dar es Salaam', 'Africa/Dar_es_Salaam'), ('Togo / Lome', 'Africa/Lome'),
        ('Tunisia / Tunis', 'Africa/Tunis'), ('Uganda / Kampala', 'Africa/Kampala'),
    ],
    'Argentina': [
        ('Argentina / Buenos Aires', 'America/Argentina/Buenos_Aires'),
        ('Argentina / Cordoba', 'America/Argentina/Cordoba'),
        ('Argentina / Mendoza', 'America/Argentina/Mendoza'),
        ('Argentina / Salta', 'America/Argentina/Salta'),
        ('Argentina / Tucuman', 'America/Argentina/Tucuman'),
        ('Argentina / Ushuaia', 'America/Argentina/Ushuaia'),
    ],
    'Asia': [
        ('Afghanistan / Kabul', 'Asia/Kabul'), ('Armenia / Yerevan', 'Asia/Yerevan'),
        ('Azerbaijan / Baku', 'Asia/Baku'), ('Bangladesh / Dhaka', 'Asia/Dhaka'),
        ('Brunei / Bandar Seri Begawan', 'Asia/Brunei'), ('Cyprus / Nicosia', 'Asia/Nicosia'),
        ('Georgia / Tbilisi', 'Asia/Tbilisi'), ('India / Kolkata', 'Asia/Kolkata'),
        ('Iran / Tehran', 'Asia/Tehran'), ('Israel / Jerusalem', 'Asia/Jerusalem'),
        ('Iraq / Baghdad', 'Asia/Baghdad'), ('Japan / Tokyo', 'Asia/Tokyo'),
        ('Jordan / Amman', 'Asia/Amman'), ('Kuwait / Al Kuwayt', 'Asia/Kuwait'),
        ('Kyrgyzstan / Bishkek', 'Asia/Bishkek'), ('Laos / Vientiane', 'Asia/Vientiane'),
        ('Lebanon / Beirut', 'Asia/Beirut'), ('Malaysia / Kuala Lumpur', 'Asia/Kuala_Lumpur'),
        ('Myanmar / Rangoon', 'Asia/Rangoon'), ('Nepal / Kathmandu', 'Asia/Kathmandu'),
        ('North Korea / Pyongyang', 'Asia/Pyongyang'), ('Oman / Muscat', 'Asia/Muscat'),
        ('Pakistan / Karachi', 'Asia/Karachi'), ('Philippines / Manila', 'Asia/Manila'),
        ('Saudi Arabia / Riyadh', 'Asia/Riyadh'), ('Singapore / Singapore', 'Asia/Singapore'),
        ('South Korea / Seoul', 'Asia/Seoul'), ('Sri Lanka / Colombo', 'Asia/Colombo'),
        ('Syria / Damascus', 'Asia/Damascus'), ('Taiwan / Taipei', 'Asia/Taipei'),
        ('Thailand / Bangkok', 'Asia/Bangkok'), ('Turkey / Istanbul', 'Asia/Istanbul'),
        ('United Arab Emirates / Dubai', 'Asia/Dubai'), ('Vietnam / Ho Chi Minh', 'Asia/Ho_Chi_Minh'),
    ],
    'Australia': [
        ('Australia / Adelaide', 'Australia/Adelaide'), ('Australia / Brisbane', 'Australia/Brisbane'),
        ('Australia / Darwin', 'Australia/Darwin'), ('Australia / Hobart', 'Australia/Hobart'),
        ('Australia / Melbourne', 'Australia/Melbourne'), ('Australia / Perth', 'Australia/Perth'),
        ('Australia / Sydney', 'Australia/Sydney'),
    ],
    'Brasil': [
        ('Brasil / Belem', 'America/Belem'), ('Brasil / Fortaleza', 'America/Fortaleza'),
        ('Brasil / Manaus', 'America/Manaus'), ('Brasil / Recife', 'America/Recife'),
        ('Brasil / Rio Branco', 'America/Rio_Branco'), ('Brasil / Sao Paulo', 'America/Sao_Paulo'),
    ],
    'Canada': [
        ('Canada / Edmonton', 'America/Edmonton'), ('Canada / Halifax', 'America/Halifax'),
        ('Canada / Montreal', 'America/Montreal'), ('Canada / Regina', 'America/Regina'),
        ('Canada / Toronto', 'America/Toronto'), ('Canada / Vancouver', 'America/Vancouver'),
        ('Canada / Winnipeg', 'America/Winnipeg'),
    ],
    'Central America': [
        ('Cuba / Havana', 'America/Havana'), ('Guatemala / Guatemala City', 'America/Guatemala'),
        ('Haiti / Port-au-Prince', 'America/Port-au-Prince'), ('Honduras / Tegucigalpa', 'America/Tegucigalpa'),
        ('Jamaica / Jamaica', 'America/Jamaica'), ('Nicaragua / Managua', 'America/Managua'),
        ('Panama / Panama', 'America/Panama'), ('Puerto Rico / San Juan', 'America/Puerto_Rico'),
    ],
    'China': [
        ('China / Hong Kong', 'Asia/Hong_Kong'), ('China / Macao', 'Asia/Macao'),
        ('China / Shanghai', 'Asia/Shanghai'), ('China / Urumqi', 'Asia/Urumqi'),
    ],
    'Europe': [
        ('Europe / Amsterdam', 'Europe/Amsterdam'), ('Europe / Athens', 'Europe/Athens'),
        ('Europe / Belgrade', 'Europe/Belgrade'), ('Europe / Berlin', 'Europe/Berlin'),
        ('Europe / Bratislava', 'Europe/Bratislava'), ('Europe / Brussels', 'Europe/Brussels'),
        ('Europe / Bucharest', 'Europe/Bucharest'), ('Europe / Budapest', 'Europe/Budapest'),
        ('Europe / Copenhagen', 'Europe/Copenhagen'), ('Europe / Dublin', 'Europe/Dublin'),
        ('Europe / Helsinki', 'Europe/Helsinki'), ('Europe / Istanbul', 'Europe/Istanbul'),
        ('Europe / Kiev', 'Europe/Kiev'), ('Europe / Lisbon', 'Europe/Lisbon'),
        ('Europe / London', 'Europe/London'), ('Europe / Luxembourg', 'Europe/Luxembourg'),
        ('Europe / Madrid', 'Europe/Madrid'), ('Europe / Minsk', 'Europe/Minsk'),
        ('Europe / Monaco', 'Europe/Monaco'), ('Europe / Moscow', 'Europe/Moscow'),
        ('Europe / Oslo', 'Europe/Oslo'), ('Europe / Paris', 'Europe/Paris'),
        ('Europe / Prague', 'Europe/Prague'), ('Europe / Riga', 'Europe/Riga'),
        ('Europe / Rome', 'Europe/Rome'), ('Europe / Sarajevo', 'Europe/Sarajevo'),
        ('Europe / Sofia', 'Europe/Sofia'), ('Europe / Stockholm', 'Europe/Stockholm'),
        ('Europe / Tallinn', 'Europe/Tallinn'), ('Europe / Tirane', 'Europe/Tirane'),
        ('Europe / Vienna', 'Europe/Vienna'), ('Europe / Vilnius', 'Europe/Vilnius'),
        ('Europe / Warsaw', 'Europe/Warsaw'), ('Europe / Zagreb', 'Europe/Zagreb'),
        ('Europe / Zurich', 'Europe/Zurich'),
    ],
    'Indonesia': [
        ('Indonesia / Jakarta', 'Asia/Jakarta'), ('Indonesia / Jayapura', 'Asia/Jayapura'),
        ('Indonesia / Makassar', 'Asia/Makassar'), ('Indonesia / Pontianak', 'Asia/Pontianak'),
    ],
    'Kazakhstan': [
        ('Kazakhstan / Almaty', 'Asia/Almaty'), ('Kazakhstan / Aqtau', 'Asia/Aqtau'),
        ('Kazakhstan / Oral', 'Asia/Oral'), ('Kazakhstan / Tashkent', 'Asia/Tashkent'),
    ],
    'Mexico': [
        ('Mexico / Cancun', 'America/Cancun'), ('Mexico / Chihuahua', 'America/Chihuahua'),
        ('Mexico / Hermosillo', 'America/Hermosillo'), ('Mexico / Mexico City', 'America/Mexico_City'),
        ('Mexico / Monterrey', 'America/Monterrey'), ('Mexico / Tijuana', 'America/Tijuana'),
    ],
    'Mongolia': [
        ('Mongolia / Ulaanbaatar', 'Asia/Ulaanbaatar'), ('Mongolia / Hovd', 'Asia/Hovd'),
    ],
    'Russia': [
        ('Russia / Irkutsk', 'Asia/Irkutsk'), ('Russia / Kamchatka', 'Asia/Kamchatka'),
        ('Russia / Krasnoyarsk', 'Asia/Krasnoyarsk'), ('Russia / Magadan', 'Asia/Magadan'),
        ('Russia / Moscow', 'Europe/Moscow'), ('Russia / Novosibirsk', 'Asia/Novosibirsk'),
        ('Russia / Vladivostok', 'Asia/Vladivostok'), ('Russia / Yekaterinburg', 'Asia/Yekaterinburg'),
    ],
    'South America': [
        ('Chile / Santiago', 'America/Santiago'), ('Columbia / Bogota', 'America/Bogota'),
        ('Ecuador / Guayaquil', 'America/Guayaquil'), ('Paraguay / Asuncion', 'America/Asuncion'),
        ('Peru / Lima', 'America/Lima'), ('Uruguay / Montevideo', 'America/Montevideo'),
        ('Venezuela / Caracas', 'America/Caracas'),
    ],
    'United States': [
        ('USA / Alaska / Anchorage', 'America/Anchorage'), ('USA / Arizona / Phoenix', 'America/Phoenix'),
        ('USA / California / Los Angeles', 'America/Los_Angeles'), ('USA / Colorado / Denver', 'America/Denver'),
        ('USA / Illinois / Chicago', 'America/Chicago'), ('USA / New York / New York City', 'America/New_York'),
        ('USA / Hawaii', 'US/Hawaii'),
    ],
    'Arctic & Antarctic': [
        ('Antarctica / Casey', 'Antarctica/Casey'), ('Antarctica / Davis', 'Antarctica/Davis'),
        ('Antarctica / South Pole', 'Antarctica/South_Pole'),
        ('Arctic / Longyearbyen', 'Arctic/Longyearbyen'),
    ],
    'Atlantic Ocean': [
        ('Atlantic / Azores', 'Atlantic/Azores'), ('Atlantic / Canary', 'Atlantic/Canary'),
        ('Atlantic / Cape Verde', 'Atlantic/Cape_Verde'), ('Atlantic / Reykjavik', 'Atlantic/Reykjavik'),
    ],
    'Pacific Ocean': [
        ('Pacific / Auckland', 'Pacific/Auckland'), ('Pacific / Fiji', 'Pacific/Fiji'),
        ('Pacific / Honolulu', 'Pacific/Honolulu'), ('Pacific / Sydney (NZ)', 'Pacific/Auckland'),
        ('Pacific / Tahiti', 'Pacific/Tahiti'), ('Pacific / Tongatapu', 'Pacific/Tongatapu'),
    ],
    'Indian Ocean': [
        ('Indian / Antananarivo', 'Indian/Antananarivo'), ('Indian / Maldives', 'Indian/Maldives'),
        ('Indian / Mauritius', 'Indian/Mauritius'), ('Indian / Reunion', 'Indian/Reunion'),
    ],
}

GROUPS = list(TIMEZONES.keys())

# Build a flat list for index-based lookup
_FLAT: list[tuple[str, str]] = []
for _g in GROUPS:
    _FLAT.extend(TIMEZONES[_g])


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def _ensure_tz_column() -> None:
    """Add timezone column to players_extra if it doesn't exist."""
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                try:
                    await cur.execute(
                        "ALTER TABLE `players_extra` ADD `Timezone` "
                        "VARCHAR(128) CHARACTER SET utf8 NULL DEFAULT NULL"
                    )
                except Exception:
                    pass  # Column already exists
    except Exception:
        pass


async def _load_player_tz(player_id: int) -> str | None:
    """Load saved timezone for a player. Returns 'Display|Zone' or None."""
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'SELECT `Timezone` FROM `players_extra` WHERE `PlayerId`=%s',
                    (player_id,))
                row = await cur.fetchone()
                if row and row[0]:
                    return str(row[0])
    except Exception:
        pass
    return None


async def _save_player_tz(player_id: int, display: str, zone: str) -> None:
    """Save player timezone preference to DB."""
    try:
        from pyxaseco.plugins.plugin_localdatabase import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    'UPDATE `players_extra` SET `Timezone`=%s WHERE `PlayerId`=%s',
                    (f'{display}|{zone}', player_id))
    except Exception as e:
        logger.debug('[RE Clock] Save TZ failed: %s', e)


# ---------------------------------------------------------------------------
# Window builder — worldmap + group list
# ---------------------------------------------------------------------------

def _build_tz_worldmap_window(current_display: str) -> str:
    """Build the worldmap window where player picks a region."""
    p = []
    p.append(f'<manialink id="{ML_SUBWIN}"></manialink>')
    p.append(f'<manialink id="{ML_WINDOW}">')
    p.append('<frame posn="-40.1 30.45 18.50">')
    p.append('<quad posn="0.8 -0.8 0.01" sizen="78.4 53.7" bgcolor="3336"/>')
    p.append('<quad posn="0.8 -0.8 0.01" sizen="78.4 53.7" bgcolor="3336"/>')
    p.append('<quad posn="-0.2 0.2 0.04" sizen="80.4 55.7" style="Bgs1InRace" substyle="BgCard3"/>')
    p.append('<quad posn="0.8 -1.3 0.02" sizen="78.4 3" bgcolor="29F9"/>')
    p.append('<quad posn="0.8 -4.3 0.03" sizen="78.4 0.1" bgcolor="FFF9"/>')
    p.append('<quad posn="1.8 -1 0.04" sizen="3.2 3.2" style="Icons128x32_1" substyle="RT_TimeAttack"/>')
    title = f'Adjust timezone for your clock. Current: $FF0{escape(current_display)}'
    p.append(f'<label posn="5.5 -1.9 0.04" sizen="74 0" textsize="2" scale="0.9" textcolor="FFFF" text="{title}"/>')
    p.append('<frame posn="77.4 1.3 0.05">')
    p.append('<quad posn="0 0 0.01" sizen="4 4" style="Icons64x64_1" substyle="ArrowDown"/>')
    p.append('<quad posn="1.1 -1.35 0.02" sizen="1.8 1.75" bgcolor="EEEF"/>')
    p.append(f'<quad posn="0.65 -0.7 0.03" sizen="2.6 2.6" action="{ML_WINDOW}" style="Icons64x64_1" substyle="Close"/>')
    p.append('</frame>')

    # Info text
    p.append('<label posn="2 -5 0.01" sizen="77 0" textsize="1" scale="1" textcolor="FFFF" autonewline="1"'
             ' text="Select your region on the worldmap below, then choose your timezone. '
             '$FF0If the worldmap is not visible, press DEL to reload."/>')

    # Worldmap image
    p.append('<frame posn="3 -10 0">')
    p.append(f'<quad posn="0 0 0.10" sizen="72 43.44" image="{WORLDMAP_URL}"/>')

    # Clickable region labels positioned over the worldmap
    regions = [
        # (group_idx, posn_x, posn_y, label)
        (0,  36.5, -24.0,  'Africa'),
        (1,  22.5, -35.6,  'Argentina'),
        (2,  45.5, -19.5,  'Asia'),
        (3,  57.5, -31.5,  'Australia'),
        (4,  22.3, -28.0,  'Brasil'),
        (5,  12.5, -11.5,  'Canada'),
        (6,  17.8, -23.0,  'Central America'),
        (7,  51.5, -18.0,  'China'),
        (8,  35.2, -15.3,  'Europe'),
        (9,  52.0, -28.5,  'Indonesia'),
        (10, 44.0, -15.4,  'Kazakhstan'),
        (11,  8.8, -21.8,  'Mexico'),
        (12, 51.0, -15.4,  'Mongolia'),
        (13, 49.0,  -9.7,  'Russia'),
        (14, 10.5, -28.7,  'South America'),
        (15, 13.5, -17.5,  'United States'),
        (16, 33.5,  -1.5,  'Arctic/Antarctic'),
        (17, 22.5, -18.6,  'Atlantic Ocean'),
        (18,  1.5, -25.0,  'Pacific Ocean'),
        (19, 44.5, -26.6,  'Indian Ocean'),
    ]
    for grp_idx, rx, ry, label in regions:
        action = ACT_GROUP_BASE + grp_idx
        p.append(f'<label posn="{rx} {ry} 0.11" sizen="8 2.3" action="{action}"'
                 f' focusareacolor1="FFF0" focusareacolor2="FFFF" text=" "/>')
        p.append(f'<label posn="{rx+0.5} {ry-0.5} 0.12" style="TextCardScores2"'
                 f' textsize="1" scale="0.55" text="$05C{escape(label)}"/>')

    p.append('</frame>')  # worldmap frame

    # Group list on the right side
    p.append('<frame posn="74 -10 0">')
    line_h = 2.2
    for gi, gname in enumerate(GROUPS):
        action = ACT_GROUP_BASE + gi
        y = line_h * gi + 1
        p.append(f'<quad posn="0 -{y} 0.10" sizen="17 2.2" action="{action}"'
                 f' style="Bgs1InRace" substyle="BgIconBorder"/>')
        p.append(f'<label posn="1 -{y+0.3} 0.11" sizen="16.5 0" textsize="1"'
                 f' scale="0.8" textcolor="05CF" text="{escape(gname)}"/>')
    p.append('</frame>')

    p.append('</frame>')  # outer window frame
    p.append('</manialink>')
    return ''.join(p)


def _build_tz_group_window(group_idx: int, current_display: str) -> str:
    """Build the timezone list for a specific region group."""
    if group_idx < 0 or group_idx >= len(GROUPS):
        return _build_tz_worldmap_window(current_display)

    group_name = GROUPS[group_idx]
    entries = TIMEZONES[group_name]

    # Compute flat offset for this group (so ACT_TZ_BASE + flat_idx selects correctly)
    flat_offset = sum(len(TIMEZONES[GROUPS[i]]) for i in range(group_idx))

    p = []
    p.append(f'<manialink id="{ML_SUBWIN}"></manialink>')
    p.append(f'<manialink id="{ML_WINDOW}">')
    p.append('<frame posn="-40.1 30.45 18.50">')
    p.append('<quad posn="0.8 -0.8 0.01" sizen="78.4 53.7" bgcolor="3336"/>')
    p.append('<quad posn="0.8 -0.8 0.01" sizen="78.4 53.7" bgcolor="3336"/>')
    p.append('<quad posn="-0.2 0.2 0.04" sizen="80.4 55.7" style="Bgs1InRace" substyle="BgCard3"/>')
    p.append('<quad posn="0.8 -1.3 0.02" sizen="78.4 3" bgcolor="29F9"/>')
    p.append('<quad posn="0.8 -4.3 0.03" sizen="78.4 0.1" bgcolor="FFF9"/>')
    p.append('<quad posn="1.8 -1 0.04" sizen="3.2 3.2" style="Icons128x32_1" substyle="RT_TimeAttack"/>')
    title = escape(f'{group_name} — select your timezone')
    p.append(f'<label posn="5.5 -1.9 0.04" sizen="74 0" textsize="2" scale="0.9" textcolor="FFFF" text="{title}"/>')

    # Back button (returns to worldmap)
    p.append('<frame posn="77.4 1.3 0.05">')
    p.append('<quad posn="1.1 -1.35 0.02" sizen="1.8 1.75" bgcolor="EEEF"/>')
    p.append(f'<quad posn="0.65 -0.7 0.03" sizen="2.6 2.6" action="{ML_WINDOW}" style="Icons64x64_1" substyle="Close"/>')
    p.append('</frame>')
    # Back-to-worldmap button
    p.append('<frame posn="52.2 -53.2 0.04">')
    p.append(f'<quad posn="6.6 0 0.01" sizen="3.2 3.2" action="{ACT_CLOCK_OPEN}" style="Icons64x64_1" substyle="ToolUp"/>')
    p.append('</frame>')

    # Timezone list (up to 20 per column, then next column)
    p.append('<frame posn="2 -6 0">')
    line_h = 2.2
    line = 0
    offset = 0.0
    for local_idx, (display_name, zone_name) in enumerate(entries):
        flat_idx = flat_offset + local_idx
        action = ACT_TZ_BASE + flat_idx
        y = line_h * line + 1
        p.append(f'<quad posn="{offset} -{y} 0.10" sizen="17 2.2" action="{action}"'
                 f' style="Bgs1InRace" substyle="BgIconBorder"/>')
        p.append(f'<label posn="{offset+1} -{y+0.3} 0.11" sizen="16.5 0" textsize="1"'
                 f' scale="0.85" textcolor="05CF" text="{escape(display_name)}"/>')
        line += 1
        if line >= 20:
            offset += 19.05
            line = 0
    p.append('</frame>')

    p.append('</frame>')
    p.append('</manialink>')
    return ''.join(p)


# ---------------------------------------------------------------------------
# Public interface used by events.py / actions.py
# ---------------------------------------------------------------------------

async def open_clock_window(aseco: 'Aseco', login: str) -> None:
    """Send the worldmap timezone picker to the player."""
    from ..config import _state
    from .common import _send
    tz = _state.player_timezone.get(login) or _state.clock.default_timezone or ''
    xml = _build_tz_worldmap_window(tz)
    await _send(aseco, login, xml)


async def open_clock_group(aseco: 'Aseco', login: str, group_idx: int) -> None:
    """Send the timezone list for a region group to the player."""
    from ..config import _state
    from .common import _send
    tz = _state.player_timezone.get(login) or _state.clock.default_timezone or ''
    xml = _build_tz_group_window(group_idx, tz)
    await _send(aseco, login, xml)


async def select_timezone(aseco: 'Aseco', login: str, flat_idx: int) -> None:
    """Apply a timezone selection, save to DB, refresh the clock."""
    from ..config import _state
    from .common import _send
    from .bar_widgets import _draw_clock_player

    if flat_idx < 0 or flat_idx >= len(_FLAT):
        return

    display_name, zone_name = _FLAT[flat_idx]
    _state.player_timezone[login] = zone_name

    # Save to DB
    player = aseco.server.players.get_player(login)
    pid = getattr(player, 'id', 0) or getattr(player, 'player_id', 0)
    if pid:
        await _save_player_tz(pid, display_name, zone_name)

    # Close the window
    close_xml = (f'<manialink id="{ML_WINDOW}"></manialink>'
                 f'<manialink id="{ML_SUBWIN}"></manialink>')
    await _send(aseco, login, close_xml)

    # Refresh clock for this player with their new timezone
    await _draw_clock_player(aseco, login)

    from .common import _send_chat
    await _send_chat(aseco, login,
        aseco.format_colors(
            f'{{#server}}>> {{#message}}Timezone set to '
            f'{{#highlite}}{display_name}{{#message}} ({zone_name})'))


async def init_clock_tz(aseco: 'Aseco') -> None:
    """Called on onSync: ensure DB column exists."""
    await _ensure_tz_column()


async def load_player_tz(aseco: 'Aseco', player) -> None:
    """Called on player connect: load saved timezone from DB."""
    from ..config import _state

    pid = getattr(player, 'id', 0) or getattr(player, 'player_id', 0)
    if not pid:
        return

    saved = await _load_player_tz(pid)
    if saved and '|' in saved:
        parts = saved.split('|', 1)
        zone = parts[1].strip()
        if zone:
            _state.player_timezone[player.login] = zone
