"""Shared player-facing command discovery and quick destinations."""

DESTINATIONS = (
    ('maps', 'Maps', (
        ('Current map', 'track'), ('Browse maps', 'list'), ('Eyepiece map list', 'elist'), ('Next map', 'nextmap'),
        ('Map queue', 'jukebox display'), ('TMX map info', 'tmxinfo'), ('Trial map info', 'trialinfo'),
    )),
    ('records', 'Records', (
        ('Local records', 'recs'), ('My local PB', 'pb'), ('Dedimania records', 'dedirecs'),
        ('RPG records', 'rpgrecs'), ('Trial records', 'trialrecs'), ('My Trial PB', 'trialpb'),
        ('Mania Records', 'wrrecs'),
    )),
    ('checkpoints', 'Checkpoints', (
        ('Checkpoint times', 'cptms'), ('Sector times', 'sectms'), ('Live standings', 'cp'),
        ('Dedimania checkpoint times', 'dedicptms'), ('Checkpoint Live help', 'cplive help'),
        ('Best checkpoint times', 'bcps help'),
        ('Run comparison help', 'ztrack help'),
    )),
    ('server', 'Server', (
        ('Server details', 'server'), ('Players', 'players'),
    )),
    ('my-ui', 'My UI', (
        ('Edit my HUD', 'hud'), ('Choose a UI style', 'uistyle list'), ('My settings', 'settings'),
        ('Reopen last window', 'lastwin'),
    )),
)


def player_command(aseco, player, name, *, include_hidden=False, include_admin=False):
    """Return a registered public command, including alias lookup."""
    registration = aseco.get_command(name)
    if registration is None or (registration.hidden and not include_hidden):
        return None
    if registration.is_admin or not registration.public:
        if not include_admin or not aseco.is_any_admin(player):
            return None
    role = registration.role
    if role == 'masteradmin' and not aseco.is_master_admin(player):
        return None
    if role == 'admin' and not (aseco.is_master_admin(player) or aseco.is_admin(player)):
        return None
    if role == 'operator' and not aseco.is_any_admin(player):
        return None
    if role not in ('', 'public', 'player', 'masteradmin', 'admin', 'operator'):
        return None
    if registration.permission and not aseco.allow_ability(player, registration.permission):
        return None
    return registration


def example_for(registration):
    for _key, _label, actions in DESTINATIONS:
        for _caption, command in actions:
            if command.partition(' ')[0] == registration.name:
                return '/' + command
    return ''


async def welcome_tools(aseco, player):
    commands = [name for name in ('bcps', 'ztrack') if player_command(aseco, player, name)]
    if not commands:
        return
    menu = 'Menu > Checkpoints, or ' if player_command(aseco, player, 'menu') else ''
    hint = '{#server}>> {#message}Checkpoint tools: ' + menu + ', '.join(
        '/' + name for name in commands) + '.'
    await aseco.client.query_ignore_result('ChatSendServerMessageToLogin', aseco.format_colors(hint), player.login)


def register(aseco):
    aseco.register_event('onPlayerConnect', welcome_tools)
