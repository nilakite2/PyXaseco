from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from pyxaseco.core.base import Component

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


COMMAND_SPECS = [
    ('setservername', 'Changes the name of the server'),
    ('setcomment', 'Changes the server comment'),
    ('setpwd', 'Changes the player password'),
    ('setspecpwd', 'Changes the spectator password'),
    ('setrefpwd', 'Changes the referee password'),
    ('setmaxplayers', 'Sets a new maximum of players'),
    ('setmaxspecs', 'Sets a new maximum of spectators'),
    ('setgamemode', 'Sets next mode {ta,rounds,team,laps,stunts,cup}'),
    ('setrefmode', 'Sets referee mode {0=top3,1=all}'),
    ('acdl', 'Sets AllowChallengeDownload {ON/OFF}'),
    ('autotime', 'Sets Auto TimeLimit {ON/OFF}'),
    ('disablerespawn', 'Disables respawn at CPs {ON/OFF}'),
    ('forceshowopp', 'Forces to show opponents {##/ALL/OFF}'),
    ('scorepanel', 'Shows automatic scorepanel {ON/OFF}'),
    ('roundsfinish', 'Shows rounds panel upon first finish {ON/OFF}'),
    ('uptodate', 'Checks whether XAseco is up to date'),
    ('rpoints', 'Sets custom Rounds points (see: /admin rpoints help)'),
    ('match', '{begin/end} to start/stop match tracking'),
    ('coppers', "Shows server's coppers amount"),
    ('pay', 'Pays server coppers to login'),
    ('wall', 'Displays popup message to all players'),
    ('mta', 'Displays popup message to all players'),
    ('pm', 'Sends private message to all available admins'),
    ('pmlog', 'Displays log of recent private admin messages'),
    ('relays', 'Displays relays list or shows relay master'),
    ('access', 'Handles player access control'),
    ('mergegbl', 'Merges a global black list {URL}'),
    ('call', 'Executes direct server call (see: /admin call help)'),
    ('unlock', 'Unlocks admin commands & features'),
    ('debug', 'Toggles debugging output'),
    ('pyres', 'Reinitializes the entire PyXaseco controller'),
    ('shutdown', 'Shuts down XASECO'),
    ('shutdownall', 'Shuts down Server & XASECO'),
]

HANDLED_SUBCOMMANDS = {name for name, _help in COMMAND_SPECS}


def can_handle(sub: str) -> bool:
    return sub in HANDLED_SUBCOMMANDS


async def handle_subcommand(
    aseco: 'Aseco',
    command: dict[str, Any],
    sub: str,
    args: list[str],
    arg: str,
    login: str,
    admin,
    logtitle: str,
    chattitle: str,
) -> bool:
    from . import command_router as admin_chat

    if sub == 'unlock':
        lock_password = admin_chat._lock_password_enabled(aseco)
        if not lock_password:
            await admin_chat._reply(aseco, login, '{#server}> {#message}Admin commands are not locked.')
            return True
        if arg.strip() == lock_password:
            admin_chat._set_unlocked(admin, True)
            aseco.console('{1} [{2}] unlocked admin commands', logtitle, login)
            await admin_chat._reply(aseco, login, '{#server}> {#message}Admin commands unlocked.')
        else:
            aseco.console('{1} [{2}] failed unlock attempt', logtitle, login)
            await admin_chat._reply(aseco, login, '{#server}> {#error}Invalid unlock password.')
        return True

    if sub == 'setservername' and arg:
        await aseco.client.query_ignore_result('SetServerName', arg)
        aseco.console('{1} [{2}] set new server name [{3}]', logtitle, login, arg)
        await admin_chat._broadcast(aseco, admin_chat._fmt_admin(aseco, admin, chattitle, 'sets servername to', arg))
        return True

    if sub == 'setcomment' and arg:
        await aseco.client.query_ignore_result('SetServerComment', arg)
        aseco.console('{1} [{2}] set server comment', logtitle, login)
        await admin_chat._reply(aseco, login, admin_chat._fmt_admin(aseco, admin, chattitle, 'sets server comment to', arg))
        return True

    if sub == 'setpwd':
        await aseco.client.query_ignore_result('SetServerPassword', arg)
        action = f'sets player password to {arg!r}' if arg else 'disables player password'
        aseco.console('{1} [{2}] {3}', logtitle, login, action)
        await admin_chat._reply(aseco, login, admin_chat._fmt_admin(aseco, admin, chattitle, action))
        return True

    if sub == 'setspecpwd':
        await aseco.client.query_ignore_result('SetServerPasswordForSpectator', arg)
        action = f'sets spectator password to {arg!r}' if arg else 'disables spectator password'
        aseco.console('{1} [{2}] {3}', logtitle, login, action)
        await admin_chat._reply(aseco, login, admin_chat._fmt_admin(aseco, admin, chattitle, action))
        return True

    if sub == 'setrefpwd':
        if getattr(aseco.server, 'game', '').upper() == 'TMF' or getattr(getattr(aseco.server, 'gameinfo', None), 'game', '').upper() == 'TMF':
            await aseco.client.query_ignore_result('SetRefereePassword', arg)
            action = f'sets referee password to {arg!r}' if arg else 'disables referee password'
            aseco.console('{1} [{2}] {3}', logtitle, login, action)
            await admin_chat._reply(aseco, login, admin_chat._fmt_admin(aseco, admin, chattitle, action))
        else:
            await admin_chat._reply(aseco, login, '{#server}> {#error}Command only available on TMF/TMUF.')
        return True

    if sub == 'setmaxplayers' and args and args[0].isdigit():
        value = int(args[0])
        await aseco.client.query_ignore_result('SetMaxPlayers', value)
        aseco.console('{1} [{2}] set new player maximum [{3}]', logtitle, login, value)
        await admin_chat._broadcast(aseco, admin_chat._fmt_admin(aseco, admin, chattitle, f'sets new player maximum to {value}!'))
        return True

    if sub == 'setmaxspecs' and args and args[0].isdigit():
        value = int(args[0])
        await aseco.client.query_ignore_result('SetMaxSpectators', value)
        aseco.console('{1} [{2}] set new spectator maximum [{3}]', logtitle, login, value)
        await admin_chat._broadcast(aseco, admin_chat._fmt_admin(aseco, admin, chattitle, f'sets new spectator maximum to {value}!'))
        return True

    if sub == 'setgamemode' and args:
        mode_name = args[0].lower()
        mode = admin_chat.GAME_MODES.get(mode_name, -1)
        if mode >= 0:
            current_mode = getattr(getattr(aseco.server, 'gameinfo', None), 'mode', None)
            changing_mode = bool(getattr(aseco, 'changingmode', False))
            if changing_mode or current_mode != mode:
                await aseco.client.query_ignore_result('SetGameMode', mode)
                setattr(aseco, 'changingmode', True)
                aseco.console('{1} [{2}] set new game mode [{3}]', logtitle, login, mode_name.upper())
                await admin_chat._broadcast(
                    aseco,
                    admin_chat._fmt_admin(aseco, admin, chattitle, f'sets next game mode to {mode_name.upper()}!')
                )
            else:
                setattr(aseco, 'changingmode', False)
                await admin_chat._reply(aseco, login, f'{{#server}}> Same game mode {{#highlite}}{mode_name.upper()}')
        else:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}Invalid game mode {{#highlite}}$i {args[0]}')
        return True

    if sub == 'setrefmode':
        if args and args[0] in ('0', '1'):
            mode = int(args[0])
            await aseco.client.query_ignore_result('SetRefereeMode', mode)
            await admin_chat._broadcast(aseco, admin_chat._fmt_admin(aseco, admin, chattitle, f'sets referee mode to {mode}!'))
        else:
            mode = await aseco.client.query('GetRefereeMode') or 0
            await admin_chat._reply(aseco, login, f'{{#server}}> Referee mode is {("All" if mode == 1 else "Top-3")}')
        return True

    if sub in ('wall', 'mta'):
        if not arg.strip():
            await admin_chat._reply(aseco, login, '{#server}> {#error}Usage: {#highlite}/admin wall <message>')
        else:
            await admin_chat._broadcast(aseco, arg.strip())
            aseco.console('{1} [{2}] wall: {3}', logtitle, login, arg.strip())
        return True

    if sub in ('coppers', 'pay'):
        await admin_chat._delegate_if_exists(
            aseco, login,
            'apps.platform_core.donate:chat_admin_donate',
            aseco, command,
            unavailable_msg='{#server}> {#admin}Coppers functions unavailable - include core/donate'
        )
        return True

    if sub == 'relays':
        await admin_chat._delegate_if_exists(
            aseco, login,
            'plugin_relay:chat_admin_relays',
            aseco, command,
            unavailable_msg='{#server}> {#admin}Relay admin unavailable.'
        )
        return True

    if sub == 'pm':
        text = arg.strip()
        if not text:
            await admin_chat._reply(aseco, login, '{#server}> {#error}Usage: {#highlite}/admin pm <message>')
        else:
            sender_nick = admin_chat.strip_colors(admin.nickname)
            line = f'{sender_nick}: {text}'
            admin_chat.PM_BUFFER.append(line[:admin_chat.PM_LINE_LEN * 4])
            del admin_chat.PM_BUFFER[:-admin_chat.PM_BUFFER_LEN]
            recipients = admin_chat._online_admin_recipients(aseco, admin)
            msg = admin_chat.format_text(
                '{#server}>> {#admin}PM from {#highlite}{1}$z$s{#admin}: {#message}{2}',
                sender_nick, text
            )
            sent = 0
            for player in recipients:
                try:
                    await admin_chat._reply(aseco, player.login, msg)
                    sent += 1
                except Exception:
                    pass
            aseco.console('{1} [{2}] pm to {3} admin recipient(s): {4}', logtitle, login, sent, text)
            await admin_chat._reply(
                aseco,
                login,
                f'{{#server}}> {{#message}}Private admin message sent to {{#highlite}}{sent}{{#message}} recipient{"s" if sent != 1 else ""}.'
            )
        return True

    if sub == 'pmlog':
        if not admin_chat.PM_BUFFER:
            await admin_chat._reply(aseco, login, '{#server}> {#message}Private admin message log is empty.')
        else:
            rows = [[f'{i + 1:02d}.', line] for i, line in enumerate(admin_chat.PM_BUFFER[-14:])]
            admin_chat.display_manialink(
                aseco, login, 'Private admin messages:',
                ['Icons128x128_1', 'ProfileAdvanced', 0.02],
                rows, [0.12, 0.88], 'OK'
            )
        return True

    if sub == 'call':
        if not args or args[0].lower() == 'help':
            await admin_chat._reply(aseco, login, '{#server}> {#message}Usage: {#highlite}/admin call <MethodName> [arg1] [arg2] ...')
            await admin_chat._reply(aseco, login, '{#server}> {#message}Use {#highlite}/admin call list{#message} to view available server methods.')
            await admin_chat._reply(aseco, login, '{#server}> {#message}Arguments support booleans, integers, floats and quoted strings automatically.')
        elif args[0].lower() == 'list':
            try:
                methods = await aseco.client.query('system.listMethods') or []
                methods = [str(method) for method in methods if method]
                methods.sort(key=str.lower)
                if not methods:
                    await admin_chat._reply(aseco, login, '{#server}> {#error}No server methods were returned.')
                else:
                    admin.msgs = [[
                        1,
                        'Available server call methods:',
                        [0.95],
                        ['Icons128x128_1', 'ProfileAdvanced', 0.02],
                    ]]
                    page = []
                    for idx, name in enumerate(methods, start=1):
                        page.append([name])
                        if idx % 15 == 0:
                            admin.msgs.append(page)
                            page = []
                    if page:
                        admin.msgs.append(page)
                    admin_chat.display_manialink_multi(aseco, admin)
            except Exception as e:
                await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}Could not list server methods: {e}')
        else:
            method = args[0]
            call_args = [admin_chat._parse_call_arg(x) for x in args[1:]]
            try:
                result = await aseco.client.query(method, *call_args)
                aseco.console('{1} [{2}] direct call {3}({4})', logtitle, login, method, call_args)
                preview = str(result)
                if len(preview) > 300:
                    preview = preview[:297] + '...'
                await admin_chat._reply(
                    aseco,
                    login,
                    f'{{#server}}> {{#message}}Call {{#highlite}}{method}{{#message}} succeeded: {{#highlite}}{preview}'
                )
            except Exception as e:
                await admin_chat._reply(
                    aseco,
                    login,
                    f'{{#server}}> {{#error}}Call {{#highlite}}{method}{{#error}} failed: {e}'
                )
        return True

    if sub == 'uptodate':
        from apps.server_info.uptodate import admin_uptodate
        await admin_uptodate(aseco, command)
        return True

    if sub == 'debug':
        current = bool(getattr(aseco, 'debug', False))
        setattr(aseco, 'debug', not current)
        await admin_chat._reply(aseco, login, f'{{#server}}> {{#message}}Debug is now {{#highlite}}{"ON" if not current else "OFF"}')
        return True

    if sub == 'pyres':
        await admin_chat._broadcast(
            aseco,
            admin_chat._fmt_admin(aseco, admin, chattitle, 'reinitializes the PyXaseco controller!')
        )
        restart_fn = getattr(aseco, 'restart', None)
        if callable(restart_fn):
            result = restart_fn()
            if asyncio.iscoroutine(result):
                await result
        else:
            await admin_chat._reply(aseco, login, '{#server}> {#error}No controller restart hook available in this runtime.')
        return True

    if sub == 'shutdown':
        await admin_chat._broadcast(
            aseco,
            admin_chat._fmt_admin(aseco, admin, chattitle, 'shuts down XASECO!')
        )
        ok = await admin_chat._best_effort_shutdown(aseco, stop_server=False)
        if not ok:
            await admin_chat._reply(aseco, login, '{#server}> {#error}No shutdown hook available in this runtime.')
        return True

    if sub == 'shutdownall':
        await admin_chat._broadcast(
            aseco,
            admin_chat._fmt_admin(aseco, admin, chattitle, 'shuts down server and XASECO!')
        )
        ok = await admin_chat._best_effort_shutdown(aseco, stop_server=True)
        if not ok:
            await admin_chat._reply(aseco, login, '{#server}> {#error}No shutdown hook available in this runtime.')
        return True

    if sub == 'mergegbl':
        url = arg.strip()
        if not url:
            await admin_chat._reply(aseco, login, '{#server}> {#error}Usage: {#highlite}/admin mergegbl <url>')
        else:
            try:
                text = await admin_chat._fetch_text_url(url)
                logins = admin_chat._extract_logins_from_text(text)
                if not logins:
                    await admin_chat._reply(aseco, login, '{#server}> {#error}No valid blacklist logins found at that URL.')
                    return True
                added = 0
                failed = 0
                for target_login in logins:
                    try:
                        await aseco.client.query_ignore_result('BlackList', target_login)
                        added += 1
                    except Exception:
                        failed += 1
                try:
                    await aseco.client.query_ignore_result('SaveBlackList', 'blacklist.txt')
                except Exception:
                    pass
                aseco.console('{1} [{2}] merged global blacklist from [{3}] added={4} failed={5}', logtitle, login, url, added, failed)
                await admin_chat._reply(
                    aseco,
                    login,
                    f'{{#server}}> {{#message}}Merged blacklist from {{#highlite}}{url}{{#message}}: '
                    f'{{#highlite}}{added}{{#message}} added, {{#highlite}}{failed}{{#message}} failed.'
                )
            except admin_chat.urllib.error.URLError as e:
                await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}Could not fetch URL: {e}')
            except Exception as e:
                await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'acdl':
        state = admin_chat._get_bool_on_off(arg)
        try:
            if state is None:
                enabled = await aseco.client.query('IsChallengeDownloadAllowed')
                await admin_chat._reply(aseco, login, f'{{#server}}> {{#admin}}AllowChallengeDownload is currently {"Enabled" if enabled else "Disabled"}')
            else:
                await aseco.client.query_ignore_result('AllowChallengeDownload', state)
                aseco.console('{1} [{2}] set AllowChallengeDownload {3} !', logtitle, login, 'ON' if state else 'OFF')
                await admin_chat._reply(aseco, login, f'{{#server}}> {{#admin}}AllowChallengeDownload set to {"Enabled" if state else "Disabled"}')
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'autotime':
        await admin_chat._delegate_if_exists(
            aseco, login,
            'skip/autotime:admin_autotime',
            aseco, admin, logtitle, chattitle, arg.strip(),
            unavailable_msg='{#server}> {#admin}Auto TimeLimit unavailable - enable the Auto Time integration'
        )
        return True

    if sub == 'scorepanel':
        state = admin_chat._get_bool_on_off(arg)
        if state is None:
            await admin_chat._reply(
                aseco, login,
                f'{{#server}}> {{#admin}}Automatic scorepanel is currently {"Enabled" if admin_chat.AUTO_SCOREPANEL else "Disabled"}'
            )
        else:
            admin_chat.AUTO_SCOREPANEL = state
            await admin_chat._reply(
                aseco, login,
                f'{{#server}}> {{#admin}}Automatic scorepanel set to {"Enabled" if state else "Disabled"}'
            )
        return True

    if sub == 'roundsfinish':
        state = admin_chat._get_bool_on_off(arg)
        if state is None:
            await admin_chat._reply(
                aseco, login,
                f'{{#server}}> {{#admin}}Rounds finish panel is currently {"Enabled" if admin_chat.ROUNDS_FINISHPANEL else "Disabled"}'
            )
        else:
            admin_chat.ROUNDS_FINISHPANEL = state
            await admin_chat._reply(
                aseco, login,
                f'{{#server}}> {{#admin}}Rounds finish panel set to {"Enabled" if state else "Disabled"}'
            )
        return True

    if sub == 'rpoints':
        await admin_chat._delegate_if_exists(
            aseco, login,
            'skip/rpoints:admin_rpoints',
            aseco, admin, logtitle, chattitle, arg.strip(),
            unavailable_msg='{#server}> {#admin}Custom Rounds points unavailable - enable the Rounds Points integration'
        )
        return True

    if sub == 'match':
        await admin_chat._delegate_if_exists(
            aseco, login,
            'plugin_matchsave:admin_match',
            aseco, admin, logtitle, chattitle, arg.strip(),
            unavailable_msg='{#server}> {#admin}Match tracking unavailable - enable the Match Save integration'
        )
        return True

    if sub == 'disablerespawn':
        state = admin_chat._get_bool_on_off(arg)
        try:
            if state is None:
                try:
                    current = await aseco.client.query('GetDisableRespawn')
                except Exception:
                    current = getattr(getattr(aseco.server, 'gameinfo', None), 'disablerespawn', None)
                if current is None:
                    await admin_chat._reply(aseco, login, '{#server}> {#error}Could not read DisableRespawn state.')
                else:
                    await admin_chat._reply(aseco, login, f'{{#server}}> {{#admin}}DisableRespawn is currently {"Enabled" if current else "Disabled"}')
            else:
                await aseco.client.query_ignore_result('SetDisableRespawn', state)
                aseco.console('{1} [{2}] set DisableRespawn {3}!', logtitle, login, 'ON' if state else 'OFF')
                await admin_chat._broadcast(
                    aseco,
                    admin_chat._fmt_admin(aseco, admin, chattitle, f'sets DisableRespawn to {"ON" if state else "OFF"}!')
                )
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'forceshowopp':
        value = arg.strip().upper()
        try:
            if not value:
                current = getattr(getattr(aseco.server, 'gameinfo', None), 'forceshowallopponents', None)
                if current is None:
                    await admin_chat._reply(aseco, login, '{#server}> {#error}Could not read ForceShowOpponents state.')
                else:
                    if current == 0:
                        shown = 'OFF'
                    elif current == -1:
                        shown = 'ALL'
                    else:
                        shown = str(current)
                    await admin_chat._reply(aseco, login, f'{{#server}}> {{#admin}}ForceShowOpponents is currently {{#highlite}}{shown}')
            else:
                if value == 'OFF':
                    number = 0
                elif value == 'ALL':
                    number = -1
                elif value.isdigit():
                    number = int(value)
                else:
                    await admin_chat._reply(aseco, login, '{#server}> {#error}Usage: {#highlite}/admin forceshowopp <OFF|ALL|number>')
                    return True
                await aseco.client.query_ignore_result('SetForceShowAllOpponents', number)
                aseco.console('{1} [{2}] set ForceShowOpponents [{3}]', logtitle, login, number)
                await admin_chat._broadcast(
                    aseco,
                    admin_chat._fmt_admin(
                        aseco, admin, chattitle,
                        f'sets ForceShowOpponents to {"OFF" if number == 0 else "ALL" if number == -1 else number}!'
                    )
                )
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    return False


def _register_specs(aseco: 'Aseco') -> None:
    for order, (name, help_text) in enumerate(COMMAND_SPECS, start=100):
        aseco.register_command(
            f'admin/{name}',
            help_text,
            is_admin=True,
            owner='chat/admin',
            app='admin',
            category='admin-server',
            parent='admin',
            usage=f'/admin {name}',
            display_name=name,
            public=name in {'help', 'helpall'},
            permission=name,
            order=order,
        )


class AdminServerDomain(Component):
    def __init__(self):
        super().__init__(
            component_id='admin.server',
            description='Server settings, runtime control, and communication admin commands.',
        )

    def register(self, aseco: 'Aseco') -> None:
        _register_specs(aseco)


SERVER_DOMAIN = AdminServerDomain()


def get_component() -> AdminServerDomain:
    return SERVER_DOMAIN


__all__ = [
    'COMMAND_SPECS',
    'HANDLED_SUBCOMMANDS',
    'can_handle',
    'handle_subcommand',
    'AdminServerDomain',
    'SERVER_DOMAIN',
    'get_component',
]
