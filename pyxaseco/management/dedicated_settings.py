"""Allowlisted TMF settings shared by setup validation and its Basic/Advanced form."""

from dataclasses import dataclass
import math

from .config_store import ManagementError


@dataclass(frozen=True)
class Setting:
    path: str
    caption: str
    kind: str = 'text'
    default: object = ''
    group: str = 'Basic'
    minimum: float = 0
    maximum: float = 1000000
    choices: tuple = ()
    secret: bool = False


SETTINGS = (
    Setting('server_options/comment', 'Server comment'),
    Setting('server_options/max_players', 'Maximum players', 'int', 32, maximum=255),
    Setting('server_options/password', 'Player password', secret=True),
    Setting('server_options/max_spectators', 'Maximum spectators', 'int', 32, maximum=255),
    Setting('server_options/password_spectator', 'Spectator password', secret=True),
    Setting('masterserver_account/validation_key', 'TMF validation key', secret=True),
    Setting('server_options/hide_server', 'Server visibility', 'choice', '0', choices=('0', '1', '2')),
    Setting('server_options/ladder_mode', 'Ladder mode', 'choice', 'forced', choices=('forced', 'inactive')),
    Setting('server_options/ladder_serverlimit_min', 'Minimum ladder points', 'int', 0, maximum=100000),
    Setting('server_options/ladder_serverlimit_max', 'Maximum ladder points', 'int', 50000, maximum=100000),
    Setting('server_options/allow_challenge_download', 'Allow map downloads', 'bool', True),
    Setting('server_options/callvote_timeout', 'Vote timeout (milliseconds)', 'int', 60000, maximum=3600000),
    Setting('server_options/callvote_ratio', 'Default vote ratio (-1 disables)', 'float', .5, minimum=-1, maximum=1),
    Setting('server_options/enable_p2p_upload', 'Allow P2P uploads', 'bool', True, 'Advanced'),
    Setting('server_options/enable_p2p_download', 'Allow P2P downloads', 'bool', True, 'Advanced'),
    Setting('server_options/autosave_replays', 'Autosave replays', 'bool', False, 'Advanced'),
    Setting('server_options/autosave_validation_replays', 'Autosave validation replays', 'bool', False, 'Advanced'),
    Setting('server_options/referee_password', 'Referee password', group='Advanced', secret=True),
    Setting('server_options/referee_validation_mode', 'Referee validation mode', 'choice', '0', 'Advanced', choices=('0', '1')),
    Setting('server_options/use_changing_validation_seed', 'Changing validation seed', 'bool', False, 'Advanced'),
    Setting('system_config/allow_spectator_relays', 'Allow spectator relays', 'bool', False, 'Advanced'),
    Setting('system_config/connection_uploadrate', 'Upload rate (Kbit/s)', 'int', 512, 'Advanced', minimum=1),
    Setting('system_config/connection_downloadrate', 'Download rate (Kbit/s)', 'int', 8192, 'Advanced', minimum=1),
    Setting('system_config/force_ip_address', 'Advertised IP address', group='Advanced'),
    Setting('system_config/bind_ip_address', 'Bind IP address', group='Advanced'),
    Setting('system_config/client_port', 'Client port (0 = automatic)', 'int', 0, 'Advanced', maximum=65535),
    Setting('system_config/p2p_cache_size', 'P2P cache size', 'int', 600, 'Advanced', maximum=100000),
    Setting('system_config/use_nat_upnp', 'Use UPnP', 'bool', False, 'Advanced'),
    Setting('system_config/packmask', 'Environment pack mask', 'text', 'stadium', 'Advanced'),
    Setting('system_config/blacklist_url', 'External blacklist URL', group='Advanced'),
    Setting('system_config/blacklist_filename', 'Blacklist filename', group='Advanced'),
    Setting('system_config/guestlist_filename', 'Guestlist filename', group='Advanced'),
    Setting('authorization/admin_password', 'Admin XML-RPC password (blank = random)', group='Advanced', secret=True),
    Setting('authorization/user_password', 'User XML-RPC password (blank = random)', group='Advanced', secret=True),
)
BY_PATH = {item.path: item for item in SETTINGS}


def validate(values):
    if not isinstance(values, dict) or values.keys() - BY_PATH.keys():
        raise ManagementError('Unknown dedicated-server setting')
    for path, value in values.items():
        item = BY_PATH[path]
        if item.kind == 'bool':
            valid = type(value) is bool
        elif item.kind in {'int', 'float'}:
            valid = (type(value) is int if item.kind == 'int' else type(value) in {int, float})
            valid = valid and math.isfinite(value) and item.minimum <= value <= item.maximum
        else:
            valid = isinstance(value, str) and len(value) <= 4096 and not any(ord(c) < 32 for c in value)
            valid = valid and (not item.choices or value in item.choices)
        if not valid:
            raise ManagementError('Invalid dedicated setting: ' + item.caption)
    lower = values.get('server_options/ladder_serverlimit_min', 0)
    upper = values.get('server_options/ladder_serverlimit_max', 50000)
    if lower > upper:
        raise ManagementError('Minimum ladder points cannot exceed maximum ladder points')
    return values


def public(values):
    return {path: ('configured' if value else 'blank') if BY_PATH[path].secret else value
            for path, value in validate(values).items()}
