"""
XML config loader for PyXaseco.

Reads config.xml, plugins.xml, adminops.xml, bannedips.xml.

The PHP Examsly parser produces a peculiar nested array structure where every
element becomes a list (even singletons).  We reproduce that same normalised
dict/list structure so downstream code can be ported directly.
"""

from __future__ import annotations
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Generic XML → dict parser (mirrors Examsly::parseXml)
# ---------------------------------------------------------------------------

def parse_xml_file(path: str | Path) -> dict:
    """
    Parse an XML file into a nested dict that mirrors Examsly's output.

    Rules:
      - Tag names are UPPERCASED (Examsly uses case-folding)
      - Every element value is stored as a list (even singletons)
      - Text content is stripped; numeric strings are kept as strings
        (callers cast as needed, matching PHP behaviour)
    """
    try:
        tree = ET.parse(str(path))
    except (ET.ParseError, FileNotFoundError, OSError) as e:
        logger.error('parse_xml_file: failed to parse %s: %s', path, e)
        return {}
    root = tree.getroot()
    return {root.tag.upper(): _element_to_dict(root)}


def _element_to_dict(elem: ET.Element) -> Any:
    """Recursively convert an Element to the Examsly-style dict."""
    children = list(elem)

    if not children:
        # Leaf node — return text (or empty string)
        return (elem.text or '').strip()

    result: dict[str, list] = {}
    for child in children:
        key = child.tag.upper()
        value = _element_to_dict(child)
        if key in result:
            result[key].append(value)
        else:
            result[key] = [value]

    return result


# ---------------------------------------------------------------------------
# Settings dataclass
# ---------------------------------------------------------------------------

class Settings:
    """
    Holds all settings from config.xml.
    Mirrors the $this->settings array and $this->server fields set by
    Aseco::loadSettings() in aseco.php.
    """

    # -- Server connection --
    server_ip: str = '127.0.0.1'
    server_port: int = 5000
    server_login: str = 'SuperAdmin'
    server_password: str = 'SuperAdmin'
    server_timeout: int = 10

# -- Feature flags using the current config key names --
    lock_password: str = ''
    cheater_action: int = 0
    script_timeout: int = 3600
    show_min_recs: int = 1
    show_recs_before: int = 0
    show_recs_after: bool = False
    show_tmxrec: bool = False
    show_playtime: bool = False
    show_curtrack: bool = False
    default_tracklist: str = 'tracklist.xml'
    topclans_minplayers: int = 2
    global_win_multiple: int = 1
    window_timeout: int = 12
    adminops_file: str = 'adminops.xml'
    bannedips_file: str = 'bannedips.xml'
    blacklist_file: str = 'blacklist.xml'
    guestlist_file: str = 'guestlist.xml'
    trackhist_file: str = 'trackhist.xml'
    admin_client: str = ''
    player_client: str = ''
    default_rpoints: str = ''
    window_style: str = ''
    admin_panel: str = ''
    donate_panel: str = ''
    records_panel: str = ''
    vote_panel: str = ''
    welcome_msg_window: bool = False
    log_all_chat: bool = False
    chatpmlog_times: bool = False
    show_recs_range: bool = False
    recs_in_window: bool = False
    rounds_in_window: bool = False
    writetracklist_random: bool = False
    help_explanation: bool = False
    lists_colornicks: bool = False
    lists_colortracks: bool = False
    display_checkpoints: bool = False
    enable_cpsspec: bool = False
    auto_enable_cps: bool = False
    auto_enable_dedicps: bool = False
    auto_admin_addip: bool = False
    afk_force_spec: bool = False
    clickable_lists: bool = False
    show_rec_logins: bool = False
    sb_stats_panels: bool = False

    def __init__(self):
        # Re-apply class defaults as instance attributes
        for key, val in self.__class__.__dict__.items():
            if not key.startswith('_') and not callable(val):
                setattr(self, key, val)

        # Chat colours and messages loaded from XML
        self.chat_colors: dict = {}
        self.chat_messages: dict = {}

        # Master admin / admin / operator lists
        self.masteradmin_list: dict = {'TMLOGIN': [], 'IPADDRESS': []}
        self.admin_list: dict = {'TMLOGIN': [], 'IPADDRESS': []}
        self.operator_list: dict = {'TMLOGIN': [], 'IPADDRESS': []}
        self.adm_abilities: list = []
        self.op_abilities: list = []

        # Banned IPs
        self.bannedips: list = []

    # -- Helpers --

    @staticmethod
    def _bool(val: Any) -> bool:
        return str(val).strip().upper() == 'TRUE'

    @staticmethod
    def _int(val: Any) -> int:
        try:
            return int(val)
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _str(val: Any) -> str:
        return str(val).strip() if val is not None else ''

    def _get(self, block: dict, key: str, default: Any = '') -> Any:
        """Safely get first element from an Examsly list."""
        items = block.get(key.upper(), [default])
        return items[0] if items else default


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def load_config(config_file: str | Path, settings: Settings) -> bool:
    """
    Parse config.xml and populate settings.
    Returns True on success.
    """
    data = parse_xml_file(config_file)
    if not data:
        logger.error('load_config: could not read/parse %s', config_file)
        return False

    try:
        root = data.get('SETTINGS', {})
        aseco = (root.get('ASECO') or [{}])[0]
        tmserver = (root.get('TMSERVER') or [{}])[0]
    except (KeyError, IndexError, TypeError) as e:
        logger.error('load_config: unexpected structure in %s: %s', config_file, e)
        return False

    g = settings._get  # shorthand

    # -- ASECO block --
    raw_colors = aseco.get('COLORS', [{}])[0] if aseco.get('COLORS') else {}
    
    settings.chat_colors = {
        key.lower(): value
        for key, value in raw_colors.items()
    }
    
    raw_msgs = aseco.get('MESSAGES', [{}])[0] if aseco.get('MESSAGES') else {}
    
    settings.chat_messages = {
        key.upper(): value
        for key, value in raw_msgs.items()
    }

    ma = aseco.get('MASTERADMINS', [{}])[0] if aseco.get('MASTERADMINS') else {}
    settings.masteradmin_list = {
        'TMLOGIN':   ma.get('TMLOGIN', []),
        'IPADDRESS': ma.get('IPADDRESS', []),
    }
    # Fill IPADDRESS list if absent
    cnt = len(settings.masteradmin_list['TMLOGIN'])
    if not settings.masteradmin_list['IPADDRESS'] and cnt:
        settings.masteradmin_list['IPADDRESS'] = [''] * cnt

    settings.lock_password           = g(aseco, 'LOCK_PASSWORD', '')
    settings.cheater_action          = settings._int(g(aseco, 'CHEATER_ACTION', 0))
    settings.script_timeout          = settings._int(g(aseco, 'SCRIPT_TIMEOUT', 3600))
    settings.show_min_recs           = settings._int(g(aseco, 'SHOW_MIN_RECS', 1))
    settings.show_recs_before        = settings._int(g(aseco, 'SHOW_RECS_BEFORE', 0))
    settings.show_recs_after         = settings._bool(g(aseco, 'SHOW_RECS_AFTER', 'false'))
    settings.show_tmxrec             = settings._bool(g(aseco, 'SHOW_TMXREC', 'false'))
    settings.show_playtime           = settings._bool(g(aseco, 'SHOW_PLAYTIME', 'false'))
    settings.show_curtrack           = settings._bool(g(aseco, 'SHOW_CURTRACK', 'false'))
    settings.default_tracklist       = g(aseco, 'DEFAULT_TRACKLIST', 'tracklist.xml')
    settings.topclans_minplayers     = settings._int(g(aseco, 'TOPCLANS_MINPLAYERS', 2))
    settings.global_win_multiple     = max(1, settings._int(g(aseco, 'GLOBAL_WIN_MULTIPLE', 1)))
    settings.window_timeout          = settings._int(g(aseco, 'WINDOW_TIMEOUT', 12))
    settings.adminops_file           = g(aseco, 'ADMINOPS_FILE', 'adminops.xml')
    settings.bannedips_file          = g(aseco, 'BANNEDIPS_FILE', 'bannedips.xml')
    settings.blacklist_file          = g(aseco, 'BLACKLIST_FILE', 'blacklist.xml')
    settings.guestlist_file          = g(aseco, 'GUESTLIST_FILE', 'guestlist.xml')
    settings.trackhist_file          = g(aseco, 'TRACKHIST_FILE', 'trackhist.xml')
    settings.admin_client            = g(aseco, 'ADMIN_CLIENT_VERSION', '')
    settings.player_client           = g(aseco, 'PLAYER_CLIENT_VERSION', '')
    settings.default_rpoints         = g(aseco, 'DEFAULT_RPOINTS', '')
    settings.window_style            = g(aseco, 'WINDOW_STYLE', '')
    settings.admin_panel             = g(aseco, 'ADMIN_PANEL', '')
    settings.donate_panel            = g(aseco, 'DONATE_PANEL', '')
    settings.records_panel           = g(aseco, 'RECORDS_PANEL', '')
    settings.vote_panel              = g(aseco, 'VOTE_PANEL', '')
    settings.welcome_msg_window      = settings._bool(g(aseco, 'WELCOME_MSG_WINDOW', 'false'))
    settings.log_all_chat            = settings._bool(g(aseco, 'LOG_ALL_CHAT', 'false'))
    settings.chatpmlog_times         = settings._bool(g(aseco, 'CHATPMLOG_TIMES', 'false'))
    settings.show_recs_range         = settings._bool(g(aseco, 'SHOW_RECS_RANGE', 'false'))
    settings.recs_in_window          = settings._bool(g(aseco, 'RECS_IN_WINDOW', 'false'))
    settings.rounds_in_window        = settings._bool(g(aseco, 'ROUNDS_IN_WINDOW', 'false'))
    settings.writetracklist_random   = settings._bool(g(aseco, 'WRITETRACKLIST_RANDOM', 'false'))
    settings.help_explanation        = settings._bool(g(aseco, 'HELP_EXPLANATION', 'false'))
    settings.lists_colornicks        = settings._bool(g(aseco, 'LISTS_COLORNICKS', 'false'))
    settings.lists_colortracks       = settings._bool(g(aseco, 'LISTS_COLORTRACKS', 'false'))
    settings.display_checkpoints     = settings._bool(g(aseco, 'DISPLAY_CHECKPOINTS', 'false'))
    settings.enable_cpsspec          = settings._bool(g(aseco, 'ENABLE_CPSSPEC', 'false'))
    settings.auto_enable_cps         = settings._bool(g(aseco, 'AUTO_ENABLE_CPS', 'false'))
    settings.auto_enable_dedicps     = settings._bool(g(aseco, 'AUTO_ENABLE_DEDICPS', 'false'))
    settings.auto_admin_addip        = settings._bool(g(aseco, 'AUTO_ADMIN_ADDIP', 'false'))
    settings.afk_force_spec          = settings._bool(g(aseco, 'AFK_FORCE_SPEC', 'false'))
    settings.clickable_lists         = settings._bool(g(aseco, 'CLICKABLE_LISTS', 'false'))
    settings.show_rec_logins         = settings._bool(g(aseco, 'SHOW_REC_LOGINS', 'false'))
    settings.sb_stats_panels         = settings._bool(g(aseco, 'SB_STATS_PANELS', 'false'))

    # -- TMSERVER block --
    settings.server_login    = g(tmserver, 'LOGIN', 'SuperAdmin')
    settings.server_password = g(tmserver, 'PASSWORD', 'SuperAdmin')
    settings.server_port     = settings._int(g(tmserver, 'PORT', 5000))
    settings.server_ip       = g(tmserver, 'IP', '127.0.0.1')
    settings.server_timeout  = settings._int(g(tmserver, 'TIMEOUT', 10))

    logger.info('load_config: loaded %s', config_file)
    return True


def load_adminops(path: str | Path, settings: Settings) -> bool:
    """
    Parse adminops.xml and populate settings.admin_list, operator_list,
    adm_abilities, op_abilities.
    """
    data = parse_xml_file(path)
    if not data:
        logger.warning('load_adminops: could not read %s', path)
        return False

    root = data.get('ADMINOPS', {})

    def _extract_list(block_key: str) -> dict:
        block = (root.get(block_key.upper()) or [{}])[0]
        if not isinstance(block, dict):
            return {'TMLOGIN': [], 'IPADDRESS': []}
        return {
            'TMLOGIN':   block.get('TMLOGIN', []),
            'IPADDRESS': block.get('IPADDRESS', []),
        }

    settings.admin_list    = _extract_list('ADMINS')
    settings.operator_list = _extract_list('OPERATORS')

    abilities_block = (root.get('ABILITIES') or [{}])[0]
    if isinstance(abilities_block, dict):
        settings.adm_abilities = abilities_block.get('ADMIN', [])
        settings.op_abilities  = abilities_block.get('OPERATOR', [])

    logger.info('load_adminops: %d admin(s), %d operator(s)',
                len(settings.admin_list['TMLOGIN']),
                len(settings.operator_list['TMLOGIN']))
    return True


def load_bannedips(path: str | Path, settings: Settings) -> bool:
    """
    Parse bannedips.xml and populate settings.bannedips.
    """
    data = parse_xml_file(path)
    if not data:
        logger.warning('load_bannedips: could not read %s', path)
        return False

    root = data.get('BANNEDIPS', {})
    settings.bannedips = root.get('IPADDRESS', [])
    logger.info('load_bannedips: %d banned IP(s)', len(settings.bannedips))
    return True


def load_plugins_list(path: str | Path) -> list[str]:
    """
    Parse plugins.xml and return list of plugin filenames.
    """
    data = parse_xml_file(path)
    if not data:
        logger.error('load_plugins_list: could not read %s', path)
        return []

    root = data.get('ASECO_PLUGINS', {})
    plugins = root.get('PLUGIN', [])
    logger.info('load_plugins_list: %d plugin(s) to load', len(plugins))
    return plugins
