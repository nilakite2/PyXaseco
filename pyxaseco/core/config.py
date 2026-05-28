"""
TOML-first config loader for PyXaseco.

Active runtime config now comes from TOML files:
  - config.toml
  - apps.toml
  - adminops.toml
  - bannedips.toml

The legacy XML parser remains available only for deferred or disabled assets.
"""

from __future__ import annotations
import logging
import os
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _load_dotenv(path: str | Path = ".env") -> None:
    """Load KEY=VALUE pairs from path into os.environ if not already set."""
    try:
        env_path = Path(path)
        if not env_path.exists():
            return
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        # .env remains optional and must never block startup.
        pass


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def display_path(path: str | Path | None, root: str | Path | None = None) -> str:
    """Return a concise display path rooted at the PyXaseco runtime folder."""
    if path is None:
        return "<none>"

    source = Path(path)

    candidates: list[Path] = []
    if root is not None:
        candidates.append(Path(root))

    if source.is_absolute():
        if source.is_dir():
            candidates.append(source)
        else:
            candidates.append(source.parent)

        current = source.parent if source.is_file() else source
        candidates.extend(current.parents)

    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if not (resolved / "config.toml").exists():
            continue
        try:
            rel = source.resolve().relative_to(resolved)
            if str(rel) == ".":
                return resolved.name
            return str(Path(resolved.name) / rel).replace("/", "\\")
        except Exception:
            continue

    return str(source)


def _lookup_path(node: Any, path: str) -> Any:
    current = node
    for part in [p for p in str(path or "").split("/") if p]:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def _set_env_default(key: str, value: Any) -> None:
    if key in os.environ:
        return
    if value is None:
        return
    if isinstance(value, list):
        text = ",".join(str(v).strip() for v in value if str(v).strip())
    else:
        text = str(value).strip()
    if text != "":
        os.environ[key] = text


def _overlay_env_from_config(data: dict[str, Any]) -> None:
    env_map = {
        "LOCK_PASSWORD": (
            "aseco/lock_password",
        ),
        "TM_LOGIN": (
            "tmserver/login",
        ),
        "TM_PASSWORD": (
            "tmserver/password",
        ),
        "TM_IP": (
            "tmserver/ip",
        ),
        "TM_PORT": (
            "tmserver/port",
        ),
        "TM_TIMEOUT": (
            "tmserver/timeout",
        ),
        "MASTERADMIN_LOGINS": (
            "masteradmins/tmlogin",
            "aseco/masteradmins/tmlogin",
        ),
        "DB_HOST": (
            "database/host",
            "localdb/host",
        ),
        "DB_PORT": (
            "database/port",
            "localdb/port",
        ),
        "DB_NAME": (
            "database/name",
            "database/db",
            "localdb/name",
            "localdb/db",
        ),
        "DB_USER": (
            "database/user",
            "localdb/user",
        ),
        "DB_PASSWORD": (
            "database/password",
            "localdb/password",
        ),
        "DEDI_LOGIN": (
            "dedimania/login",
            "records_dedimania/login",
        ),
        "DEDI_PASSWORD": (
            "dedimania/password",
            "records_dedimania/password",
        ),
        "DEDI_NATION": (
            "dedimania/nation",
            "records_dedimania/nation",
        ),
        "MK_NATION": (
            "mania_karma/nation",
            "ui/karma/nation",
        ),
        "PUBLIC_STATS_API_BASE": (
            "public_stats/api_base",
            "server_info/public_stats/api_base",
        ),
        "PUBLIC_STATS_API_TOKEN": (
            "public_stats/api_token",
            "server_info/public_stats/api_token",
        ),
        "DISCORD_ADMIN_WEBHOOK_URL": (
            "discord_webhook/admin_webhook_url",
            "discord_webhook/config/discord_webhook/admin_webhook_url",
            "discord/config/discord_webhook/admin_webhook_url",
        ),
        "DISCORD_CHAT_WEBHOOK_URL": (
            "discord_webhook/chat_webhook_url",
            "discord_webhook/config/discord_webhook/chat_webhook_url",
            "discord/config/discord_webhook/chat_webhook_url",
        ),
        "DISCORD_ADMIN_WEBHOOK_NAME": (
            "discord_webhook/admin_webhook_name",
            "discord_webhook/config/discord_webhook/admin_webhook_name",
            "discord/config/discord_webhook/admin_webhook_name",
        ),
        "DISCORD_CHAT_WEBHOOK_NAME": (
            "discord_webhook/chat_webhook_name",
            "discord_webhook/config/discord_webhook/chat_webhook_name",
            "discord/config/discord_webhook/chat_webhook_name",
        ),
    }

    for env_key, candidates in env_map.items():
        for candidate in candidates:
            value = _lookup_path(data, candidate)
            if value is not None:
                _set_env_default(env_key, value)
                break


def load_toml_file(path: str | Path) -> dict:
    try:
        with Path(path).open('rb') as fh:
            data = tomllib.load(fh)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError) as e:
        logger.error('load_toml_file: failed to parse %s: %s', path, e)
        return {}


# ---------------------------------------------------------------------------
# Generic XML parser retained for deferred/disabled legacy assets
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
        # Leaf node â€” return text (or empty string)
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
    Holds all active runtime settings.
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
    show_recs_after: int = 0
    show_tmxrec: int = 0
    show_playtime: int = 0
    show_curtrack: int = 0
    default_tracklist: str = 'MatchSettings.txt'
    topclans_minplayers: int = 2
    global_win_multiple: int = 1
    window_timeout: int = 12
    adminops_file: str = 'adminops.toml'
    bannedips_file: str = 'bannedips.toml'
    blacklist_file: str = 'blacklist.txt'
    guestlist_file: str = 'guestlist.txt'
    trackhist_file: str = 'trackhist.txt'
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
        self.adm_abilities: dict = {}
        self.op_abilities: dict = {}
        self.admin_abilities: dict = {}

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
    Parse config.toml and populate settings.
    Returns True on success.
    """
    cfg_path = Path(config_file)
    _load_dotenv(cfg_path.parent / ".env")
    _load_dotenv(".env")

    data = load_toml_file(cfg_path)
    if not data:
        logger.error('load_config: could not read/parse %s', config_file)
        return False
    _overlay_env_from_config(data)
    aseco = data.get('aseco', {})
    tmserver = data.get('tmserver', {})

    settings.chat_colors = {}
    settings.chat_messages = {}

    masteradmins = data.get('masteradmins', {}) or aseco.get('masteradmins', {}) or {}
    logins = list(masteradmins.get('tmlogin', []) or [])
    ip_addrs = list(masteradmins.get('ipaddress', []) or [])
    while len(ip_addrs) < len(logins):
        ip_addrs.append('')
    settings.masteradmin_list = {
        'TMLOGIN': logins,
        'IPADDRESS': ip_addrs,
    }

    settings.lock_password = _env("LOCK_PASSWORD") or str(aseco.get('lock_password', ''))
    settings.server_login = _env("TM_LOGIN") or str(tmserver.get('login', 'SuperAdmin'))
    settings.server_password = _env("TM_PASSWORD") or str(tmserver.get('password', 'SuperAdmin'))
    settings.server_port = settings._int(_env("TM_PORT") or tmserver.get('port', 5000))
    settings.server_ip = _env("TM_IP") or str(tmserver.get('ip', '127.0.0.1'))
    settings.server_timeout = settings._int(_env("TM_TIMEOUT") or tmserver.get('timeout', 10))

    extra_masteradmins = [x.strip() for x in (_env("MASTERADMIN_LOGINS") or "").split(",") if x.strip()]
    for login in extra_masteradmins:
        if login not in settings.masteradmin_list['TMLOGIN']:
            settings.masteradmin_list['TMLOGIN'].append(login)
            settings.masteradmin_list['IPADDRESS'].append('')

    try:
        from pyxaseco.message_loader import overlay_colors, overlay_core
        overlay_colors(settings, cfg_path.parent)
        overlay_core(settings, cfg_path.parent)
    except Exception as exc:
        logger.warning('load_config: messages config overlay failed: %s', exc)

    try:
        from pyxaseco.settings_loader import overlay_server
        overlay_server(settings, cfg_path.parent)
    except Exception as exc:
        logger.warning('load_config: settings config overlay failed: %s', exc)

    logger.info('load_config: loaded %s', display_path(cfg_path))
    return True


def load_adminops(path: str | Path, settings: Settings) -> bool:
    """
    Parse adminops.toml and populate settings admin/operator lists and abilities.
    """
    data = load_toml_file(path)
    if not data:
        logger.warning('load_adminops: could not read %s', path)
        return False
    def _extract_list(key: str) -> dict:
        block = data.get(key, {}) or {}
        logins = list(block.get('tmlogin', []) or [])
        ips = list(block.get('ipaddress', []) or [])
        while len(ips) < len(logins):
            ips.append('')
        return {'TMLOGIN': logins, 'IPADDRESS': ips}

    masters = _extract_list('masteradmins')
    if masters['TMLOGIN'] or masters['IPADDRESS']:
        settings.masteradmin_list = masters
    settings.admin_list = _extract_list('admins')
    settings.operator_list = _extract_list('operators')

    abilities = data.get('abilities', {}) or {}
    admin_abilities = {str(k).upper(): [bool(v)] for k, v in (abilities.get('admin', {}) or {}).items()}
    operator_abilities = {str(k).upper(): [bool(v)] for k, v in (abilities.get('operator', {}) or {}).items()}
    settings.adm_abilities = admin_abilities
    settings.op_abilities = operator_abilities
    settings.admin_abilities = {str(k).lower(): bool(v[0]) for k, v in admin_abilities.items()}

    logger.info('load_adminops: %d admin(s), %d operator(s)',
                len(settings.admin_list['TMLOGIN']),
                len(settings.operator_list['TMLOGIN']))
    return True


def load_bannedips(path: str | Path, settings: Settings) -> bool:
    """
    Parse bannedips.toml and populate settings.bannedips.
    """
    data = load_toml_file(path)
    if not data:
        logger.warning('load_bannedips: could not read %s', path)
        return False

    settings.bannedips = list(data.get('ipaddress', []) or data.get('banned_ips', []) or [])
    logger.info('load_bannedips: %d banned IP(s)', len(settings.bannedips))
    return True


def load_apps_list(path: str | Path) -> list[str]:
    """
    Parse apps.toml and return the active app loadout.
    """
    data = load_toml_file(path)
    if not data:
        logger.error('load_apps_list: could not read %s', path)
        return []

    root = data.get('loadout', {}) or {}
    apps = list(root.get('enabled', []) or [])
    logger.info('load_apps_list: %d app entry(s) to load', len(apps))
    return apps



