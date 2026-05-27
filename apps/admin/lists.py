from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pyxaseco.core.base import Component

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


COMMAND_SPECS = [
    ('help', 'Shows all available /admin commands', True),
    ('helpall', 'Displays help for available /admin commands', True),
    ('players', 'Displays list of known players'),
    ('showbanlist', 'Displays current ban list'),
    ('listbans', 'Displays current ban list'),
    ('showiplist', 'Displays current banned IPs list'),
    ('listips', 'Displays current banned IPs list'),
    ('showblacklist', 'Displays current black list'),
    ('listblacks', 'Displays current black list'),
    ('showguestlist', 'Displays current guest list'),
    ('listguests', 'Displays current guest list'),
    ('writeiplist', 'Saves current banned IPs list'),
    ('readiplist', 'Loads current banned IPs list'),
    ('cleaniplist', 'Cleans current banned IPs list'),
    ('writeblacklist', 'Saves current black list'),
    ('readblacklist', 'Loads current black list'),
    ('cleanblacklist', 'Cleans current black list'),
    ('writeguestlist', 'Saves current guest list'),
    ('readguestlist', 'Loads current guest list'),
    ('cleanguestlist', 'Cleans current guest list'),
    ('cleanbanlist', 'Cleans current ban list'),
    ('mutelist', 'Displays global mute/ignore list'),
    ('listmutes', 'Displays global mute/ignore list'),
    ('ignorelist', 'Displays global mute/ignore list'),
    ('listignores', 'Displays global mute/ignore list'),
    ('cleanmutes', 'Cleans global mute/ignore list'),
    ('cleanignores', 'Cleans global mute/ignore list'),
    ('listmasters', 'Displays current masteradmin list', True),
    ('listadmins', 'Displays current admin list', True),
    ('listops', 'Displays current operator list', True),
    ('adminability', 'Shows/changes admin ability {ON/OFF}'),
    ('opability', 'Shows/changes operator ability {ON/OFF}'),
    ('listabilities', 'Displays current abilities list'),
    ('writeabilities', 'Saves current admin/operator abilities'),
    ('readabilities', 'Loads admin/operator abilities'),
    ('panel', 'Selects admin panel (see: /admin panel help)'),
    ('style', 'Selects default window style'),
    ('admpanel', 'Selects default admin panel'),
    ('donpanel', 'Selects default donate panel'),
    ('recpanel', 'Selects default records panel'),
    ('votepanel', 'Selects default vote panel'),
]

HANDLED_SUBCOMMANDS = {name for name, _help, *_rest in COMMAND_SPECS}


def can_handle(sub: str) -> bool:
    return sub in HANDLED_SUBCOMMANDS


def _show_admin_list_window(
    admin_chat,
    aseco: 'Aseco',
    admin,
    header: str,
    icon: list,
    table_header: list[str],
    entries: list[list],
    widths: list[float],
) -> None:
    pages = []
    page = [table_header]
    lines = 0

    for row in entries:
        page.append(row)
        lines += 1
        if lines >= 14:
            pages.append(page)
            page = [table_header]
            lines = 0

    if len(page) > 1:
        pages.append(page)

    admin.msgs = [[1, header, widths, icon]]
    admin.msgs.extend(pages or [[table_header]])
    admin_chat.display_manialink_multi(aseco, admin)


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

    if sub == 'help':
        cmds_list = admin_chat._visible_admin_commands_for_player(aseco, admin)
        if cmds_list:
            head = aseco.format_colors('{#interact}Currently supported subcommands for /admin, /ad, /a, //:\n')
            msg = head + ', '.join(name for name, _ in cmds_list)
            msg += aseco.format_colors('\n{#interact}Use {#highlite}/admin helpall{#interact} for descriptions.')
        else:
            msg = '{#server}> {#error}No commands available.'

        await admin_chat._reply(aseco, login, msg)
        return True

    if sub == 'helpall':
        visible = admin_chat._visible_admin_commands_for_player(aseco, admin)
        rows = [[name, help_text] for name, help_text in visible]
        pages = [rows[i:i + 14] for i in range(0, max(len(rows), 1), 14)]
        admin.msgs = [[
            1,
            'Currently supported /admin subcommands:',
            [1.2, 0.3, 0.9],
            ['Icons128x128_1', 'ProfileAdvanced', 0.02]
        ]]
        admin.msgs.extend(pages)
        admin_chat.display_manialink_multi(aseco, admin)
        return True

    if sub == 'players':
        online = aseco.server.players.all()
        if not online:
            await admin_chat._reply(aseco, login, '{#server}> {#error}No players online.')
            return True

        admin.playerlist = [{'login': p.login, 'nickname': p.nickname} for p in online]

        def _action_cell(label: str, action_id: int | None):
            if action_id is None:
                return label
            return [label, action_id]

        rows = [[
            'Id',
            '{#nick}Nick $g/{#login} Login',
            'Warn',
            'Ignore',
            'Kick',
            'Ban',
            'Black',
            'Guest',
            'Spec',
        ]]

        muted = {
            str(x).strip().lower()
            for x in (getattr(aseco.server, 'mutelist', []) or [])
        }

        try:
            black_entries = await aseco.client.query('GetBlackList', 300, 0) or []
        except Exception:
            black_entries = []

        try:
            guest_entries = await aseco.client.query('GetGuestList', 300, 0) or []
        except Exception:
            guest_entries = []

        black_logins = {
            str(b.get('Login', '')).strip().lower()
            for b in black_entries if isinstance(b, dict)
        }
        guest_logins = {
            str(g.get('Login', '')).strip().lower()
            for g in guest_entries if isinstance(g, dict)
        }

        for i, pl in enumerate(online, 1):
            login_l = pl.login.lower()
            role_level = admin_chat._role_level(aseco, pl.login)

            ignore_cell = (
                _action_cell('$f93Unignore', admin_chat.ML_UNIGNORE_BASE + i)
                if login_l in muted
                else _action_cell('$f93Ignore', admin_chat.ML_IGNORE_BASE + i)
            )

            black_cell = (
                _action_cell('$f03Unblack', admin_chat.ML_UNBLACK_BASE + i)
                if login_l in black_logins
                else _action_cell('$f03Black', admin_chat.ML_BLACK_BASE + i)
            )

            guest_cell = (
                _action_cell('$3c3Remove', admin_chat.ML_REMOVEGUEST_BASE + i)
                if login_l in guest_logins
                else _action_cell('$3c3Add', admin_chat.ML_ADDGUEST_BASE + i)
            )

            spec_cell = (
                '$09cSpec'
                if getattr(pl, 'isspectator', False)
                else _action_cell('$09fForce', admin_chat.ML_FORCESPEC_BASE + i)
            )

            if role_level > 0:
                player_cell = f'{{#black}}{admin_chat.strip_colors(pl.nickname)}$z / {{#logina}}{pl.login}'
            else:
                player_cell = f'{{#black}}{admin_chat.strip_colors(pl.nickname)}$z / {{#login}}{pl.login}'

            rows.append([
                f'{i:02d}.',
                player_cell,
                _action_cell('$ff3Warn', admin_chat.ML_WARN_BASE + i),
                ignore_cell,
                _action_cell('$c3fKick', admin_chat.ML_KICK_BASE + i),
                _action_cell('$f30Ban', admin_chat.ML_BAN_BASE + i),
                black_cell,
                guest_cell,
                spec_cell,
            ])

        pages = [rows[k:k + 15] for k in range(0, len(rows), 15)]
        admin.msgs = [[
            1,
            'Current Players:',
            [1.49, 0.15, 0.5, 0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.12],
            ['Icons128x128_1', 'Buddies']
        ]]
        admin.msgs.extend(pages)
        admin_chat.display_manialink_multi(aseco, admin)
        return True

    if sub in ('showbanlist', 'listbans'):
        try:
            bans = await aseco.client.query('GetBanList', 100, 0) or []
            if bans:
                admin.playerlist = [
                    {'login': b.get('Login', ''), 'nickname': b.get('NickName', '')}
                    for b in bans
                ]
                header = 'Current Ban List:'
                rows = []
                for i, b in enumerate(bans, 1):
                    rows.append([
                        f'{i:02d}.',
                        b.get('Login', ''),
                        admin_chat.strip_colors(b.get('NickName', '')),
                        ['{#highlite}UNBAN', admin_chat.ML_LIST_UNBAN_BASE + i],
                    ])
                _show_admin_list_window(
                    admin_chat, aseco, admin, header,
                    ['Icons64x64_1', 'NotBuddy'],
                    ['#', 'Login', 'Nick', 'Action'],
                    rows,
                    [1.10, 0.12, 0.42, 0.40, 0.16],
                )
            else:
                await admin_chat._reply(aseco, login, '{#server}> Ban list is empty.')
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('showblacklist', 'listblacks'):
        try:
            bl = await aseco.client.query('GetBlackList', 100, 0) or []
            if bl:
                admin.playerlist = [
                    {'login': b.get('Login', ''), 'nickname': b.get('NickName', '')}
                    for b in bl
                ]
                header = 'Current Black List:'
                rows = []
                for i, b in enumerate(bl, 1):
                    rows.append([
                        f'{i:02d}.',
                        b.get('Login', ''),
                        admin_chat.strip_colors(b.get('NickName', '')),
                        ['{#highlite}UNBLACK', admin_chat.ML_LIST_UNBLACK_BASE + i],
                    ])
                _show_admin_list_window(
                    admin_chat, aseco, admin, header,
                    ['Icons64x64_1', 'NotBuddy'],
                    ['#', 'Login', 'Nick', 'Action'],
                    rows,
                    [1.10, 0.12, 0.42, 0.40, 0.16],
                )
            else:
                await admin_chat._reply(aseco, login, '{#server}> Black list is empty.')
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('showiplist', 'listips'):
        try:
            ips = admin_chat._get_bannedips_state(aseco)
            if ips:
                admin.iplist = list(ips)
                header = 'Banned IPs:'
                rows = []
                for i, ip in enumerate(ips, 1):
                    rows.append([
                        f'{i:02d}.',
                        ip,
                        ['{#highlite}UNBAN', admin_chat.ML_UNBANIP_NEG_BASE - i],
                    ])
                _show_admin_list_window(
                    admin_chat, aseco, admin, header,
                    ['Icons64x64_1', 'NotBuddy'],
                    ['#', 'IP Address', 'Action'],
                    rows,
                    [1.00, 0.12, 0.68, 0.20],
                )
            else:
                await admin_chat._reply(aseco, login, '{#server}> No banned IPs.')
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('showguestlist', 'listguests'):
        try:
            gl = await aseco.client.query('GetGuestList', 100, 0) or []
            if gl:
                admin.playerlist = [
                    {'login': g.get('Login', ''), 'nickname': g.get('NickName', '')}
                    for g in gl
                ]
                header = 'Current Guest List:'
                rows = []
                for i, g in enumerate(gl, 1):
                    rows.append([
                        f'{i:02d}.',
                        g.get('Login', ''),
                        admin_chat.strip_colors(g.get('NickName', '')),
                        ['{#highlite}REMOVE', admin_chat.ML_LIST_REMOVEGUEST_BASE + i],
                    ])
                _show_admin_list_window(
                    admin_chat, aseco, admin, header,
                    ['Icons128x128_1', 'Invite'],
                    ['#', 'Login', 'Nick', 'Action'],
                    rows,
                    [1.10, 0.12, 0.42, 0.40, 0.16],
                )
            else:
                await admin_chat._reply(aseco, login, '{#server}> Guest list is empty.')
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('cleanbanlist',):
        try:
            await aseco.client.query_ignore_result('CleanBanList')
            await admin_chat._reply(aseco, login, '{#server}> Ban list cleaned.')
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('cleaniplist',):
        try:
            for ip in admin_chat._get_bannedips_state(aseco):
                try:
                    await aseco.client.query_ignore_result('UnBanIP', ip)
                except Exception:
                    pass
            admin_chat._set_bannedips_state(aseco, [])
            await admin_chat._write_bannedips_toml(aseco)
            await admin_chat._reply(aseco, login, '{#server}> Banned IPs list cleaned.')
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('cleanblacklist',):
        try:
            await aseco.client.query_ignore_result('CleanBlackList')
            await admin_chat._reply(aseco, login, '{#server}> Black list cleaned.')
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('cleanguestlist',):
        try:
            await aseco.client.query_ignore_result('CleanGuestList')
            await admin_chat._reply(aseco, login, '{#server}> Guest list cleaned.')
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('writeblacklist',):
        try:
            await aseco.client.query_ignore_result('SaveBlackList', 'blacklist.txt')
            await admin_chat._reply(aseco, login, '{#server}> Black list saved.')
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('readblacklist',):
        try:
            await aseco.client.query_ignore_result('LoadBlackList', 'blacklist.txt')
            await admin_chat._reply(aseco, login, '{#server}> Black list loaded.')
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('writeguestlist',):
        try:
            await aseco.client.query_ignore_result('SaveGuestList', 'guestlist.txt')
            await admin_chat._reply(aseco, login, '{#server}> Guest list saved.')
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('readguestlist',):
        try:
            await aseco.client.query_ignore_result('LoadGuestList', 'guestlist.txt')
            await admin_chat._reply(aseco, login, '{#server}> Guest list loaded.')
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('writeiplist',):
        try:
            path = await admin_chat._write_bannedips_toml(aseco)
            if path:
                await admin_chat._reply(aseco, login, '{#server}> Banned IPs list saved to {#highlite}bannedips.toml')
            else:
                await admin_chat._reply(aseco, login, '{#server}> {#error}Could not save banned IPs list.')
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('readiplist',):
        try:
            ok = await admin_chat._read_bannedips_toml(aseco)
            if ok:
                await admin_chat._reply(aseco, login, '{#server}> Banned IPs list loaded from {#highlite}bannedips.toml')
            else:
                await admin_chat._reply(aseco, login, '{#server}> {#error}Could not load banned IPs list.')
        except Exception as e:
            await admin_chat._reply(aseco, login, f'{{#server}}> {{#error}}{e}')
        return True

    if sub in ('mutelist', 'listmutes', 'ignorelist', 'listignores'):
        ml = list(getattr(aseco.server, 'mutelist', []))
        if ml:
            admin.playerlist = [{'login': lgn, 'nickname': lgn} for lgn in ml]
            header = 'Global Mute/Ignore List:'
            rows = []
            for i, lgn in enumerate(ml, 1):
                rows.append([f'{i:02d}.', lgn, ['{#highlite}UNMUTE', admin_chat.ML_LIST_UNIGNORE_BASE + i]])
            _show_admin_list_window(
                admin_chat, aseco, admin, header,
                ['Icons64x64_1', 'NotBuddy'],
                ['#', 'Login', 'Action'],
                rows,
                [1.00, 0.12, 0.68, 0.20],
            )
        else:
            await admin_chat._reply(aseco, login, '{#server}> Mute list is empty.')
        return True

    if sub in ('cleanmutes', 'cleanignores'):
        aseco.server.mutelist = []
        await admin_chat._reply(aseco, login, '{#server}> Mute list cleared.')
        return True

    if sub == 'listmasters':
        masters = aseco.settings.masteradmin_list.get('TMLOGIN', [])
        master_names = await admin_chat._admin_display_names(aseco, masters)
        await admin_chat._reply(
            aseco,
            login,
            '{#server}> MasterAdmins: ' +
            ', '.join(f'{{#highlite}}{m}{{#message}}' for m in master_names),
        )
        return True

    if sub == 'listadmins':
        admins = aseco.settings.admin_list.get('TMLOGIN', [])
        admin_names = await admin_chat._admin_display_names(aseco, admins)
        await admin_chat._reply(
            aseco,
            login,
            '{#server}> Admins: ' +
            ', '.join(f'{{#highlite}}{a}{{#message}}' for a in admin_names),
        )
        return True

    if sub == 'listops':
        ops = aseco.settings.operator_list.get('TMLOGIN', [])
        op_names = await admin_chat._admin_display_names(aseco, ops)
        await admin_chat._reply(
            aseco,
            login,
            '{#server}> Operators: ' +
            ', '.join(f'{{#highlite}}{o}{{#message}}' for o in op_names),
        )
        return True

    if sub == 'adminability':
        if not admin_chat._is_masteradmin_player(aseco, admin):
            await admin_chat._reply(
                aseco,
                login,
                '{#server}> {#error}Only MasterAdmins may change admin abilities.'
            )
            return True

        if not args:
            await admin_chat._reply(
                aseco,
                login,
                '{#server}> Usage: {#highlite}/admin adminability <command> [ON|OFF]'
            )
        else:
            ability = args[0].lower().lstrip('/')
            if len(args) >= 2 and args[1].upper() in ('ON', 'OFF'):
                enabled = args[1].upper() == 'ON'
                admin_chat._set_ability_enabled(aseco, 'admin', ability, enabled)
                admin_chat._write_adminops_toml(aseco)
                aseco.console(
                    '{1} [{2}] set admin ability [{3}] = {4}',
                    logtitle, login, ability, 'ON' if enabled else 'OFF'
                )
                await admin_chat._broadcast(
                    aseco,
                    admin_chat._fmt_admin(
                        aseco,
                        admin,
                        chattitle,
                        f'sets admin ability {ability} to {"ON" if enabled else "OFF"}!'
                    )
                )
            else:
                state = 'ON' if admin_chat._ability_enabled(aseco, 'admin', ability) else 'OFF'
                await admin_chat._reply(
                    aseco,
                    login,
                    f'{{#server}}> Admin ability {{#highlite}}{ability}{{#message}} is {{#highlite}}{state}'
                )
        return True

    if sub == 'opability':
        if not admin_chat._is_masteradmin_player(aseco, admin):
            await admin_chat._reply(
                aseco,
                login,
                '{#server}> {#error}Only MasterAdmins may change operator abilities.'
            )
            return True

        if not args:
            await admin_chat._reply(
                aseco,
                login,
                '{#server}> Usage: {#highlite}/admin opability <command> [ON|OFF]'
            )
        else:
            ability = args[0].lower().lstrip('/')
            if len(args) >= 2 and args[1].upper() in ('ON', 'OFF'):
                enabled = args[1].upper() == 'ON'
                admin_chat._set_ability_enabled(aseco, 'op', ability, enabled)
                admin_chat._write_adminops_toml(aseco)
                aseco.console(
                    '{1} [{2}] set operator ability [{3}] = {4}',
                    logtitle, login, ability, 'ON' if enabled else 'OFF'
                )
                await admin_chat._broadcast(
                    aseco,
                    admin_chat._fmt_admin(
                        aseco,
                        admin,
                        chattitle,
                        f'sets operator ability {ability} to {"ON" if enabled else "OFF"}!'
                    )
                )
            else:
                state = 'ON' if admin_chat._ability_enabled(aseco, 'op', ability) else 'OFF'
                await admin_chat._reply(
                    aseco,
                    login,
                    f'{{#server}}> Operator ability {{#highlite}}{ability}{{#message}} is {{#highlite}}{state}'
                )
        return True

    if sub == 'listabilities':
        rows = admin_chat._ability_rows(aseco)
        pages = [rows[i:i + 14] for i in range(0, max(len(rows), 1), 14)]
        admin.msgs = [[
            1,
            'Admin / Operator abilities:',
            [1.2, 0.45, 0.25, 0.25],
            ['Icons128x128_1', 'ProfileAdvanced', 0.02]
        ]]
        admin.msgs.extend(pages)
        admin_chat.display_manialink_multi(aseco, admin)
        return True

    if sub == 'writeabilities':
        if admin_chat._viewer_role_level(aseco, admin) < 2:
            await admin_chat._reply(
                aseco,
                login,
                '{#server}> {#error}Only Admins or MasterAdmins may write abilities.'
            )
            return True

        path = admin_chat._write_adminops_toml(aseco)
        if path:
            await admin_chat._reply(
                aseco,
                login,
                f'{{#server}}> Abilities saved to {{#highlite}}{path.name}'
            )
        else:
            await admin_chat._reply(
                aseco,
                login,
                '{#server}> {#error}Could not save abilities.'
            )
        return True

    if sub == 'readabilities':
        if admin_chat._viewer_role_level(aseco, admin) < 2:
            await admin_chat._reply(
                aseco,
                login,
                '{#server}> {#error}Only Admins or MasterAdmins may read abilities.'
            )
            return True

        ok = admin_chat._read_adminops_toml(aseco)
        if ok:
            await admin_chat._reply(
                aseco,
                login,
                '{#server}> Abilities loaded from {#highlite}adminops.toml'
            )
        else:
            await admin_chat._reply(
                aseco,
                login,
                '{#server}> {#error}Could not load abilities.'
            )
        return True

    if sub == 'access':
        if not args:
            await admin_chat._reply(
                aseco,
                login,
                '{#server}> Usage: {#highlite}/admin access <player/login/id>'
            )
        else:
            target_login = admin_chat._find_player_login_by_id_or_name(aseco, admin, args[0])
            if not target_login:
                await admin_chat._reply(aseco, login, '{#server}> {#error}Player not found.')
            else:
                is_master = target_login in aseco.settings.masteradmin_list.get('TMLOGIN', [])
                is_admin_ = target_login in aseco.settings.admin_list.get('TMLOGIN', [])
                is_op = target_login in aseco.settings.operator_list.get('TMLOGIN', [])
                is_muted = target_login in getattr(aseco.server, 'mutelist', [])

                guest_list = []
                black_list = []
                try:
                    guest_list = await aseco.client.query('GetGuestList', 300, 0) or []
                except Exception:
                    pass
                try:
                    black_list = await aseco.client.query('GetBlackList', 300, 0) or []
                except Exception:
                    pass

                is_guest = any(g.get('Login', '') == target_login for g in guest_list if isinstance(g, dict))
                is_black = any(b.get('Login', '') == target_login for b in black_list if isinstance(b, dict))

                header = f'Access for {target_login}:'
                rows = [
                    ['MasterAdmin', '{#green}YES' if is_master else '{#error}NO'],
                    ['Admin',       '{#green}YES' if is_admin_ else '{#error}NO'],
                    ['Operator',    '{#green}YES' if is_op else '{#error}NO'],
                    ['Guest',       '{#green}YES' if is_guest else '{#error}NO'],
                    ['Blacklisted', '{#green}YES' if is_black else '{#error}NO'],
                    ['Muted',       '{#green}YES' if is_muted else '{#error}NO'],
                ]
                admin_chat.display_manialink(
                    aseco, login, header,
                    ['Icons128x128_1', 'ProfileAdvanced', 0.02],
                    rows, [0.9, 0.4, 0.5], 'OK'
                )
        return True

    if sub == 'panel':
        panel_command = {
            'author': admin,
            'command': 'admin',
            'params': arg.strip(),
        }
        await admin_chat._delegate_if_exists(
            aseco, login,
            'apps.platform_ui.panels:admin_panel',
            aseco, panel_command,
            unavailable_msg='{#server}> {#admin}Panel command unavailable - enable app/platform_ui'
        )
        return True

    if sub in ('style', 'admpanel', 'donpanel', 'recpanel', 'votepanel'):
        await admin_chat._delegate_if_exists(
            aseco, login,
            'apps.platform_ui.panels:chat_panel_pref',
            aseco, command,
            unavailable_msg='{#server}> {#admin}Panel preferences unavailable - enable app/platform_ui'
        )
        return True

    return False


def _register_specs(aseco: 'Aseco') -> None:
    for order, item in enumerate(COMMAND_SPECS, start=400):
        name, help_text, *rest = item
        public = bool(rest[0]) if rest else False
        aseco.register_command(
            f'admin/{name}',
            help_text,
            is_admin=True,
            owner='chat/admin',
            app='admin',
            category='admin-lists',
            parent='admin',
            usage=f'/admin {name}',
            display_name=name,
            public=public,
            permission=name,
            order=order,
        )


class AdminListsDomain(Component):
    def __init__(self):
        super().__init__(
            component_id='admin.lists',
            description='Help, list, abilities, and panel-selection admin commands.',
        )

    def register(self, aseco: 'Aseco') -> None:
        _register_specs(aseco)


LISTS_DOMAIN = AdminListsDomain()


def get_component() -> AdminListsDomain:
    return LISTS_DOMAIN


__all__ = [
    'COMMAND_SPECS',
    'HANDLED_SUBCOMMANDS',
    'can_handle',
    'handle_subcommand',
    'AdminListsDomain',
    'LISTS_DOMAIN',
    'get_component',
]
