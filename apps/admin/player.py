from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pyxaseco.core.base import Component

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


COMMAND_SPECS = [
    ('warn', 'Sends a kick/ban warning to a player'),
    ('kick', 'Kicks a player from server'),
    ('kickghost', 'Kicks a ghost player from server'),
    ('ban', 'Bans a player from server'),
    ('unban', 'UnBans a player from server'),
    ('banip', 'Bans an IP address from server'),
    ('unbanip', 'UnBans an IP address from server'),
    ('black', 'Blacklists a player from server'),
    ('unblack', 'UnBlacklists a player from server'),
    ('addguest', 'Adds a guest player to server'),
    ('removeguest', 'Removes a guest player from server'),
    ('forceteam', 'Forces player into {Blue} or {Red} team'),
    ('forcespec', 'Forces player into free spectator'),
    ('specfree', 'Forces spectator into free mode'),
    ('mute', 'Adds a player to global mute/ignore list'),
    ('ignore', 'Adds a player to global mute/ignore list'),
    ('unmute', 'Removes a player from global mute/ignore list'),
    ('unignore', 'Removes a player from global mute/ignore list'),
    ('addadmin', 'Adds a new admin'),
    ('removeadmin', 'Removes an admin'),
    ('addop', 'Adds a new operator'),
    ('removeop', 'Removes an operator'),
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

    if sub == 'warn':
        target = await admin_chat._get_player_param(aseco, admin, arg, offline=True)
        if target:
            if not admin_chat._is_connected_player(aseco, target):
                await admin_chat._deny_offline_target(aseco, admin, target.login)
                return True
            if not admin_chat._can_target_player(aseco, admin, target):
                await admin_chat._deny_protected_target(aseco, admin, target.login)
                return True
            msg = admin_chat.format_text(
                '{#server}>> {#error}Warning: {#highlite}{1}$z$s{#error} - you risk being kicked or banned!',
                admin_chat.strip_colors(target.nickname)
            )
            await aseco.client.query_ignore_result('ChatSendServerMessage', aseco.format_colors(msg))
            aseco.console('{1} [{2}] warned [{3}]', logtitle, login, target.login)
        return True

    if sub == 'kick':
        target = await admin_chat._get_player_param(aseco, admin, arg, offline=True)
        if target:
            if not admin_chat._is_connected_player(aseco, target):
                await admin_chat._deny_offline_target(aseco, admin, target.login)
                return True
            if not admin_chat._can_target_player(aseco, admin, target):
                await admin_chat._deny_protected_target(aseco, admin, target.login)
                return True
            aseco.console('{1} [{2}] kicked [{3}]', logtitle, login, target.login)
            await admin_chat._broadcast(
                aseco,
                admin_chat._fmt_admin(aseco, admin, chattitle, 'kicks', admin_chat.strip_colors(target.nickname))
            )
            await aseco.client.query_ignore_result('Kick', target.login)
        return True

    if sub == 'kickghost':
        target_login = arg.strip()
        if target_login:
            if not admin_chat._can_target_login(aseco, admin, target_login):
                await admin_chat._deny_protected_target(aseco, admin, target_login)
                return True
            try:
                await aseco.client.query_ignore_result('Kick', target_login)
                aseco.console('{1} [{2}] kicked ghost [{3}]', logtitle, login, target_login)
                await admin_chat._reply(aseco, login, f'{{#server}}> Kicked ghost: {{#highlite}}{target_login}')
            except Exception as e:
                await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'ban':
        target = await admin_chat._get_player_param(aseco, admin, arg, offline=True)
        if target:
            if not admin_chat._can_target_player(aseco, admin, target):
                await admin_chat._deny_protected_target(aseco, admin, target.login)
                return True
            aseco.console('{1} [{2}] banned [{3}]', logtitle, login, target.login)
            await admin_chat._broadcast(
                aseco,
                admin_chat._fmt_admin(aseco, admin, chattitle, 'bans', admin_chat.strip_colors(target.nickname))
            )
            await aseco.client.query_ignore_result('Ban', target.login)
        return True

    if sub == 'unban':
        target = await admin_chat._get_player_param(aseco, admin, arg, offline=True)
        if target:
            if not admin_chat._can_target_login(aseco, admin, target.login):
                await admin_chat._deny_protected_target(aseco, admin, target.login)
                return True
            try:
                await aseco.client.query_ignore_result('UnBan', target.login)
                aseco.console('{1} [{2}] unbanned [{3}]', logtitle, login, target.login)
                await admin_chat._reply(aseco, login, f'{{#server}}> Unbanned: {{#highlite}}{target.login}')
            except Exception as e:
                await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'banip':
        ip = arg.strip()
        if ip:
            try:
                await aseco.client.query_ignore_result('BanIP', ip)
                banned = admin_chat._get_bannedips_state(aseco)
                if ip.lower() not in {item.lower() for item in banned}:
                    banned.append(ip)
                admin_chat._set_bannedips_state(aseco, banned)
                await admin_chat._write_bannedips_toml(aseco)
                aseco.console('{1} [{2}] banned IP [{3}]', logtitle, login, ip)
                await admin_chat._reply(aseco, login, f'{{#server}}> Banned IP: {{#highlite}}{ip}')
            except Exception as e:
                await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'unbanip':
        ip = arg.strip()
        if ip:
            try:
                await aseco.client.query_ignore_result('UnBanIP', ip)
                banned = [
                    item for item in admin_chat._get_bannedips_state(aseco)
                    if item.lower() != ip.lower()
                ]
                admin_chat._set_bannedips_state(aseco, banned)
                await admin_chat._write_bannedips_toml(aseco)
                aseco.console('{1} [{2}] unbanned IP [{3}]', logtitle, login, ip)
                await admin_chat._reply(aseco, login, f'{{#server}}> Unbanned IP: {{#highlite}}{ip}')
            except Exception as e:
                await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'black':
        target = await admin_chat._get_player_param(aseco, admin, arg, offline=True)
        if target:
            if not admin_chat._can_target_player(aseco, admin, target):
                await admin_chat._deny_protected_target(aseco, admin, target.login)
                return True
            try:
                await aseco.client.query_ignore_result('BlackList', target.login)
                await aseco.client.query_ignore_result('SaveBlackList', 'blacklist.txt')
                aseco.console('{1} [{2}] blacklisted [{3}]', logtitle, login, target.login)
                await admin_chat._broadcast(
                    aseco,
                    admin_chat._fmt_admin(aseco, admin, chattitle, 'blacklists', admin_chat.strip_colors(target.nickname))
                )
                if admin_chat._is_connected_player(aseco, target):
                    await aseco.client.query_ignore_result('Kick', target.login)
            except Exception as e:
                await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'unblack':
        target = await admin_chat._get_player_param(aseco, admin, arg, offline=True)
        if target:
            if not admin_chat._can_target_login(aseco, admin, target.login):
                await admin_chat._deny_protected_target(aseco, admin, target.login)
                return True
            try:
                await aseco.client.query_ignore_result('UnBlackList', target.login)
                await aseco.client.query_ignore_result('SaveBlackList', 'blacklist.txt')
                aseco.console('{1} [{2}] unblacklisted [{3}]', logtitle, login, target.login)
                await admin_chat._reply(aseco, login, f'{{#server}}> UnBlacklisted: {{#highlite}}{target.login}')
            except Exception as e:
                await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'addguest':
        target = await admin_chat._get_player_param(aseco, admin, arg, offline=True)
        if target:
            if not admin_chat._can_target_login(aseco, admin, target.login):
                await admin_chat._deny_protected_target(aseco, admin, target.login)
                return True
            try:
                await aseco.client.query_ignore_result('AddGuest', target.login)
                await aseco.client.query_ignore_result('SaveGuestList', 'guestlist.txt')
                aseco.console('{1} [{2}] added guest [{3}]', logtitle, login, target.login)
                await admin_chat._reply(aseco, login, f'{{#server}}> Added guest: {{#highlite}}{target.login}')
            except Exception as e:
                await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'removeguest':
        target = await admin_chat._get_player_param(aseco, admin, arg, offline=True)
        if target:
            if not admin_chat._can_target_login(aseco, admin, target.login):
                await admin_chat._deny_protected_target(aseco, admin, target.login)
                return True
            try:
                await aseco.client.query_ignore_result('RemoveGuest', target.login)
                await aseco.client.query_ignore_result('SaveGuestList', 'guestlist.txt')
                aseco.console('{1} [{2}] removed guest [{3}]', logtitle, login, target.login)
                await admin_chat._reply(aseco, login, f'{{#server}}> Removed guest: {{#highlite}}{target.login}')
            except Exception as e:
                await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('mute', 'ignore'):
        target = await admin_chat._get_player_param(aseco, admin, arg, offline=True)
        if target:
            if not admin_chat._is_connected_player(aseco, target):
                await admin_chat._deny_offline_target(aseco, admin, target.login)
                return True
            if not admin_chat._can_target_player(aseco, admin, target):
                await admin_chat._deny_protected_target(aseco, admin, target.login)
                return True
            try:
                await aseco.client.query_ignore_result('Ignore', target.login)
                if target.login not in aseco.server.mutelist:
                    aseco.server.mutelist.append(target.login)
                aseco.console('{1} [{2}] muted [{3}]', logtitle, login, target.login)
                await admin_chat._broadcast(
                    aseco,
                    admin_chat._fmt_admin(aseco, admin, chattitle, 'mutes', admin_chat.strip_colors(target.nickname))
                )
            except Exception as e:
                await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('unmute', 'unignore'):
        target = await admin_chat._get_player_param(aseco, admin, arg, offline=True)
        if target:
            if not admin_chat._can_target_login(aseco, admin, target.login):
                await admin_chat._deny_protected_target(aseco, admin, target.login)
                return True
            try:
                await aseco.client.query_ignore_result('UnIgnore', target.login)
                if target.login in aseco.server.mutelist:
                    aseco.server.mutelist.remove(target.login)
                aseco.console('{1} [{2}] unmuted [{3}]', logtitle, login, target.login)
                await admin_chat._broadcast(aseco, admin_chat._fmt_admin(aseco, admin, chattitle, 'unmutes', target.login))
            except Exception as e:
                await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'addadmin':
        if not admin_chat._is_masteradmin_player(aseco, admin):
            await admin_chat._reply(aseco, login, '{#server}> {#error}Only MasterAdmins may add admins.')
            return True
        target = await admin_chat._get_player_param(aseco, admin, arg, offline=True)
        if target:
            if admin_chat._role_level(aseco, target.login) >= 3:
                await admin_chat._reply(
                    aseco, login,
                    f'{{#server}}> {{#error}}Cannot add {{#highlite}}{target.login}{{#error}} as Admin because this login is already a MasterAdmin.'
                )
                return True
            admins = aseco.settings.admin_list.get('TMLOGIN', [])
            ops = aseco.settings.operator_list.get('TMLOGIN', [])
            changed = False
            if target.login not in admins:
                admins.append(target.login)
                aseco.settings.admin_list['TMLOGIN'] = admins
                changed = True
            if target.login in ops:
                ops.remove(target.login)
                aseco.settings.operator_list['TMLOGIN'] = ops
                changed = True
            if changed:
                admin_chat._write_adminops_toml(aseco)
            aseco.console('{1} [{2}] added admin [{3}]', logtitle, login, target.login)
            target_name = await admin_chat._admin_display_name(aseco, target.login)
            await admin_chat._reply(aseco, login, f'{{#server}}> Added admin: {{#highlite}}{target_name}')
        return True

    if sub == 'removeadmin':
        if not admin_chat._is_masteradmin_player(aseco, admin):
            await admin_chat._reply(aseco, login, '{#server}> {#error}Only MasterAdmins may remove admins.')
            return True
        target = await admin_chat._get_player_param(aseco, admin, arg, offline=True)
        if target:
            admins = aseco.settings.admin_list.get('TMLOGIN', [])
            removed = False
            if target.login in admins:
                admins.remove(target.login)
                aseco.settings.admin_list['TMLOGIN'] = admins
                removed = True
            if removed:
                admin_chat._write_adminops_toml(aseco)
                aseco.console('{1} [{2}] removed admin [{3}]', logtitle, login, target.login)
                target_name = await admin_chat._admin_display_name(aseco, target.login)
                await admin_chat._reply(aseco, login, f'{{#server}}> Removed admin: {{#highlite}}{target_name}')
            else:
                await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}Login is not an admin: {{#highlite}}{target.login}')
        return True

    if sub == 'addop':
        if admin_chat._viewer_role_level(aseco, admin) < 2:
            await admin_chat._reply(aseco, login, '{#server}> {#error}Only Admins or MasterAdmins may add operators.')
            return True
        target = await admin_chat._get_player_param(aseco, admin, arg, offline=True)
        if target:
            target_level = admin_chat._role_level(aseco, target.login)
            if target_level >= 2:
                await admin_chat._reply(
                    aseco, login,
                    f'{{#server}}> {{#error}}Cannot add {{#highlite}}{target.login}{{#error}} as Operator because this login is already Admin or MasterAdmin.'
                )
                return True
            ops = aseco.settings.operator_list.get('TMLOGIN', [])
            if target.login not in ops:
                ops.append(target.login)
                aseco.settings.operator_list['TMLOGIN'] = ops
                admin_chat._write_adminops_toml(aseco)
            aseco.console('{1} [{2}] added operator [{3}]', logtitle, login, target.login)
            target_name = await admin_chat._admin_display_name(aseco, target.login)
            await admin_chat._reply(aseco, login, f'{{#server}}> Added operator: {{#highlite}}{target_name}')
        return True

    if sub == 'removeop':
        if admin_chat._viewer_role_level(aseco, admin) < 2:
            await admin_chat._reply(aseco, login, '{#server}> {#error}Only Admins or MasterAdmins may remove operators.')
            return True
        target = await admin_chat._get_player_param(aseco, admin, arg, offline=True)
        if target:
            if admin_chat._viewer_role_level(aseco, admin) < 3 and admin_chat._role_level(aseco, target.login) >= 2:
                await admin_chat._reply(
                    aseco, login,
                    f'{{#server}}> {{#error}}Cannot remove operator access from {{#highlite}}{target.login}{{#error}} because this login is Admin or MasterAdmin.'
                )
                return True
            ops = aseco.settings.operator_list.get('TMLOGIN', [])
            removed = False
            if target.login in ops:
                ops.remove(target.login)
                aseco.settings.operator_list['TMLOGIN'] = ops
                removed = True
            if removed:
                admin_chat._write_adminops_toml(aseco)
                aseco.console('{1} [{2}] removed operator [{3}]', logtitle, login, target.login)
                target_name = await admin_chat._admin_display_name(aseco, target.login)
                await admin_chat._reply(aseco, login, f'{{#server}}> Removed operator: {{#highlite}}{target_name}')
            else:
                await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}Login is not an operator: {{#highlite}}{target.login}')
        return True

    if sub == 'forcespec':
        target = await admin_chat._get_player_param(aseco, admin, arg, offline=True)
        if target:
            if not admin_chat._is_connected_player(aseco, target):
                await admin_chat._deny_offline_target(aseco, admin, target.login)
                return True
            if not admin_chat._can_target_player(aseco, admin, target):
                await admin_chat._deny_protected_target(aseco, admin, target.login)
                return True
            try:
                await aseco.client.query_ignore_result('ForceSpectator', target.login, 1)
                await aseco.client.query_ignore_result('ForceSpectator', target.login, 0)
                await aseco.client.query_ignore_result('ForceSpectatorTarget', target.login, '', 2)
                aseco.console('{1} [{2}] forced spectator [{3}]', logtitle, login, target.login)
                await admin_chat._broadcast(
                    aseco,
                    admin_chat._fmt_admin(aseco, admin, chattitle, 'forces to spectator', admin_chat.strip_colors(target.nickname))
                )
            except Exception as e:
                await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'specfree':
        target = await admin_chat._get_player_param(aseco, admin, arg, offline=True)
        if target:
            if not admin_chat._is_connected_player(aseco, target):
                await admin_chat._deny_offline_target(aseco, admin, target.login)
                return True
            if not admin_chat._can_target_player(aseco, admin, target):
                await admin_chat._deny_protected_target(aseco, admin, target.login)
                return True
            try:
                await aseco.client.query_ignore_result('ForceSpectator', target.login, 2)
                aseco.console('{1} [{2}] set free spectator [{3}]', logtitle, login, target.login)
                await admin_chat._broadcast(
                    aseco,
                    admin_chat._fmt_admin(aseco, admin, chattitle, 'sets free spectator for', admin_chat.strip_colors(target.nickname))
                )
            except Exception as e:
                await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub == 'forceteam':
        await admin_chat._reply(aseco, login, '{#server}> {#error}/admin forceteam is not implemented yet.')
        return True

    return False


def _register_specs(aseco: 'Aseco') -> None:
    for order, (name, help_text) in enumerate(COMMAND_SPECS, start=300):
        aseco.register_command(
            f'admin/{name}',
            help_text,
            is_admin=True,
            owner='chat/admin',
            app='admin',
            category='admin-player',
            parent='admin',
            usage=f'/admin {name}',
            display_name=name,
            public=False,
            permission=name,
            order=order,
        )


class AdminPlayerDomain(Component):
    def __init__(self):
        super().__init__(
            component_id='admin.player',
            description='Player moderation, guesting, mute, and role management commands.',
        )

    def register(self, aseco: 'Aseco') -> None:
        _register_specs(aseco)


PLAYER_DOMAIN = AdminPlayerDomain()


def get_component() -> AdminPlayerDomain:
    return PLAYER_DOMAIN


__all__ = [
    'COMMAND_SPECS',
    'HANDLED_SUBCOMMANDS',
    'can_handle',
    'handle_subcommand',
    'AdminPlayerDomain',
    'PLAYER_DOMAIN',
    'get_component',
]
