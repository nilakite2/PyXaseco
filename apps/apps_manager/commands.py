"""In-game Apps Manager action and slash-command routing."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING, Any

from pyxaseco.management.app_policy import MANAGEABLE_STANDALONE_APPS, PROTECTED_STANDALONE_APPS
from pyxaseco.toml_tools import move_loadout_entry
from .service import (
    get_service, _apps_toml_path, _apps_dir, _normalize_app_name, _can_configure_app,
    _discover_config_apps, _config_item_owner, _is_masteradmin, _standalone_loadout_state,
    _standalone_paths, _is_manageable_standalone_app, _standalone_status, _archive_destination,
    _restart_required_message, _reload_done_message, _unknown_apps_target, _update_config_field,
    _config_app_counts, _find_config_item, _config_save_mode, _reload_app_runtime, _apply_config_toggle,
    _reply, _reply_apps_usage, _runtime_status, _mark_config_pending,
    _ui_config_group_for, _config_item_target_info, _config_field_write_path,
)
from .views import (
    _apps_action_map, _show_package_review_window, _show_apps_manager_window,
    _preview_scope, _show_app_config_window, _show_item_edit_window, _show_preview_selector,
)

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


async def handle_apps_action(aseco: 'Aseco', admin, answer: list[Any]) -> bool:
    try:
        return await _handle_apps_action(aseco, admin, answer)
    except (ValueError, OSError) as error:
        await _reply(aseco, getattr(admin, 'login', ''), '{#server}> {#error}Configuration not applied: ' + str(error))
        return True


async def _handle_apps_action(aseco: 'Aseco', admin, answer: list[Any]) -> bool:
    if not answer or len(answer) < 3:
        return False
    action_id = int(answer[2])
    payload = _apps_action_map(admin).get(int(action_id))
    if not payload:
        return False

    login = getattr(admin, 'login', '')
    if not _is_masteradmin(aseco, admin, login):
        await _reply(aseco, login, '{#server}> {#error}Only MasterAdmins may use the apps manager.')
        return True

    kind = payload[0]

    if kind in {'confirm_release', 'apply_release'}:
        plan = getattr(admin, '_release_review', None)
        if plan and tuple(payload[1:]) == (plan['package'], plan['review'], plan['force']):
            if kind == 'confirm_release':
                _show_package_review_window(aseco, admin, plan, confirm=True)
            else:
                service = get_service(aseco)
                if service is not None:
                    _apps_action_map(admin).pop(action_id, None)
                    await service.releases(aseco, admin, plan['package'], install=True,
                                           reviewed=plan['review'], force=plan['force'])
        return True

    if kind in {'check_releases', 'stage_release', 'review_release', 'force_review'}:
        service = get_service(aseco)
        if service is not None:
            await service.releases(aseco, admin, str(payload[1]) if kind != 'check_releases' else None,
                                   review=kind in {'review_release', 'force_review'}, force=kind == 'force_review')
        return True

    if kind in {'open_config', 'open_edit', 'toggle_config', 'adjust_field', 'reload_app', 'score_preview',
                'preview_menu', 'preview_select'}:
        app_key = str(payload[1])
        if not _can_configure_app(aseco, app_key):
            await _reply(aseco, login, '{#server}> {#error}App ' + app_key +
                         ' is not enabled and loaded, or its files are absent. No configuration was changed.')
            return True

    if kind == 'open_config':
        _show_app_config_window(aseco, admin, str(payload[1]), str(payload[2]) if len(payload) > 2 else None)
        return True

    if kind == 'apps_home':
        _show_apps_manager_window(aseco, admin)
        return True

    if kind == 'open_edit':
        _show_item_edit_window(aseco, admin, str(payload[1]), str(payload[2]))
        return True

    if kind == 'score_preview':
        app_key = str(payload[1])
        await _score_preview(aseco, admin, table=app_key == 'alternate_scoretable')
        item_key = str(payload[2])
        if item_key:
            _show_item_edit_window(aseco, admin, app_key, item_key)
        else:
            _show_app_config_window(aseco, admin, app_key, str(payload[3]) if len(payload) > 3 else None)
        return True

    if kind in {'preview_menu', 'preview_select'}:
        if kind == 'preview_select':
            from apps.ui.score_preview import PreviewSelection
            phase, mode = payload[2:4]
            await _score_preview(aseco, admin, phase != 'off', selection=PreviewSelection(phase, mode))
        _show_preview_selector(aseco, admin)
        return True

    if kind == 'reload_app':
        app_key = str(payload[1])
        if await _reload_app_runtime(aseco, app_key):
            _mark_config_pending(aseco, app_key, False)
            await _refresh_score_preview(aseco, admin)
            await _reply(aseco, login, _reload_done_message(f'app/{app_key}'))
        else:
            await _reply(aseco, login, _restart_required_message(f'app/{app_key}'))
        _show_apps_manager_window(aseco, admin)
        return True

    if kind == 'toggle_app':
        action, name = str(payload[1]), str(payload[2])
        move_loadout_entry(_apps_toml_path(aseco), f'app/{name}', action == 'enable')
        await _reply(aseco, login, _restart_required_message(f"app/{name} {action}d in apps.toml"))
        _show_apps_manager_window(aseco, admin)
        return True

    if kind == 'archive_app':
        name = str(payload[1])
        if name in PROTECTED_STANDALONE_APPS:
            await _reply(aseco, login, '{#server}> {#error}App files are protected; use Enable/Disable instead.')
            return True
        app_dir, _archived = _standalone_paths(aseco, name)
        if app_dir.exists():
            move_loadout_entry(_apps_toml_path(aseco), f'app/{name}', False)
            shutil.move(str(app_dir), str(_archive_destination(aseco, name)))
            await _reply(aseco, login, _restart_required_message(f'app/{name} moved to apps/00removed and disabled'))
        _show_apps_manager_window(aseco, admin)
        return True

    if kind == 'restore_app':
        name = str(payload[1])
        if name in PROTECTED_STANDALONE_APPS:
            await _reply(aseco, login, '{#server}> {#error}App files are protected; use Enable/Disable instead.')
            return True
        app_dir, archived = _standalone_paths(aseco, name)
        if archived is not None:
            _apps_dir(aseco).mkdir(parents=True, exist_ok=True)
            shutil.move(str(archived), str(app_dir))
            move_loadout_entry(_apps_toml_path(aseco), f'app/{name}', True)
            await _reply(aseco, login, _restart_required_message(f'app/{name} restored from apps/00removed and enabled'))
        _show_apps_manager_window(aseco, admin)
        return True

    if kind == 'toggle_config':
        app_key, item_key, enabled = str(payload[1]), str(payload[2]), bool(payload[3])
        scope = payload[4] if len(payload) > 4 else None
        group = _ui_config_group_for(item_key) if app_key == 'ui' else None
        item = _find_config_item(aseco, app_key, item_key)
        if item and _preview_target_changed(aseco, admin, app_key, item, 'enabled', scope):
            await _preview_changed(aseco, admin)
            _show_app_config_window(aseco, admin, app_key, group)
            return True
        msg = await _apply_config_toggle(aseco, app_key, item_key, enabled, scope=scope)
        await _refresh_score_preview(aseco, admin)
        await _reply(aseco, login, msg)
        _show_app_config_window(aseco, admin, app_key, group)
        return True

    if kind == 'adjust_field':
        app_key = str(payload[1])
        item_key = str(payload[2])
        field_key = str(payload[3])
        delta = float(payload[4])
        item = _find_config_item(aseco, app_key, item_key)
        if not item:
            await _reply(aseco, login, _unknown_apps_target(item_key))
            return True

        scope = payload[5] if len(payload) > 5 else None
        if _preview_target_changed(aseco, admin, app_key, item, field_key, scope):
            await _preview_changed(aseco, admin)
            _show_item_edit_window(aseco, admin, app_key, item_key)
            return True
        action_text = _update_config_field(aseco, item, field_key, delta, scope=scope)
        if _config_save_mode(aseco, app_key, item_key) == 'reload' and await _reload_app_runtime(aseco, app_key, item_key):
            await _reply(aseco, login, _reload_done_message(action_text))
        else:
            _mark_config_pending(aseco, app_key)
            await _reply(aseco, login, _restart_required_message(action_text))
        await _refresh_score_preview(aseco, admin)
        _show_item_edit_window(aseco, admin, app_key, item_key)
        return True

    return False


async def _refresh_score_preview(aseco, admin):
    preview = aseco.get_service('ui/score_preview')
    if preview:
        await preview.refresh(aseco, admin)


def _preview_target_changed(aseco, admin, app_key, item, field_key, original_scope):
    current = _preview_scope(aseco, admin, app_key)
    if original_scope is not None:
        return original_scope != current
    if current is None:
        return False
    # An editor opened before the preview may still be on screen.
    old = _config_item_target_info(aseco, item)
    new = _config_item_target_info(aseco, item, scope=current)
    return _config_field_write_path(item, old, field_key) != _config_field_write_path(item, new, field_key)


async def _preview_changed(aseco, admin):
    await _reply(aseco, admin.login, '{#server}> {#message}The preview changed. Check the editor before adjusting again.')


async def _score_preview(aseco, admin, visibility=None, *, table=False, selection=None):
    preview = aseco.get_service('ui/score_preview')
    if preview is None or not _can_configure_app(aseco, 'ui'):
        await _reply(aseco, admin.login, '{#server}> {#error}Layout preview requires Eyepiece UI.')
        return
    table = table or (selection is not None and selection.phase == 'table')
    if table and not aseco.has_service('ui/score_preview/alternate_scoretable'):
        await _reply(aseco, admin.login, '{#server}> {#error}Alternate Scoretable is not loaded.')
        return
    visible = not preview.visible(admin, table=table) if visibility is None else visibility
    if table and selection is None:
        from apps.ui.score_preview import PreviewSelection
        current = preview.selection(admin)
        selection = PreviewSelection('table', current.mode_key if current else 'current')
    if not await preview.set_visible(aseco, admin, visible, selection=selection):
        await _reply(aseco, admin.login, '{#server}> {#message}The scoreboard is already open. Preview during a race.')


async def _handle_apps_command(aseco: 'Aseco', login: str, admin, args: list[str]) -> None:
    try:
        await _dispatch_apps_command(aseco, login, admin, args)
    except (ValueError, OSError) as error:
        await _reply(aseco, login, '{#server}> {#error}Configuration not applied: ' + str(error))


async def _dispatch_apps_command(aseco: 'Aseco', login: str, admin, args: list[str]) -> None:
    if not _is_masteradmin(aseco, admin, login):
        await _reply(aseco, login, '{#server}> {#error}Only MasterAdmins may change app and feature states.')
        return

    if not args or str(args[0]).strip().lower() == 'list':
        _show_apps_manager_window(aseco, admin)
        return

    action = str(args[0]).strip().lower()
    name = _normalize_app_name(args[1]) if len(args) > 1 else ''
    if action in ('preview', 'scorepreview'):
        preview = aseco.get_service('ui/score_preview')
        if not preview or not _can_configure_app(aseco, 'ui'):
            await _score_preview(aseco, admin)
            return
        if action == 'preview' and len(args) == 1:
            _show_preview_selector(aseco, admin)
            return
        from apps.ui.score_preview import PREVIEW_MODES, PREVIEW_PHASES, PreviewSelection

        mode = str(args[2]).lower().replace('-', '_') if len(args) > 2 else 'current'
        mode = 'time_attack' if mode == 'ta' else mode
        if (len(args) > 3 or (name and name not in (*PREVIEW_PHASES, 'on', 'off'))
                or mode not in (*PREVIEW_MODES, 'current') or (name == 'off' and len(args) > 2)):
            await _reply(aseco, login, '{#server}> {#message}Usage: //apps preview <race|score|table|off> '
                         '[current|ta|rounds|team|laps|stunts|cup]')
            return
        visible = name != 'off' if name else not preview.visible(admin)
        phase = 'score' if name == 'on' or not name else name
        await _score_preview(aseco, admin, visible, selection=PreviewSelection(phase, mode))
        return
    if action == 'update':
        options = [str(arg).lower() for arg in args[2:]]
        if not name or options not in ([], ['force'], ['confirm'], ['force', 'confirm']):
            await _reply(aseco, login, '{#server}> {#message}Usage: //apps update <package> [force] [confirm]')
            return
        service = get_service(aseco)
        if service is not None:
            confirmed = 'confirm' in options
            await service.releases(aseco, admin, name, review=not confirmed,
                                   install=confirmed, force='force' in options)
        return
    if action in {'updates', 'download', 'review'}:
        if (action == 'updates' and len(args) != 1) or (action != 'updates' and len(args) != 2):
            await _reply(aseco, login, '{#server}> {#message}Usage: //apps updates | //apps download <package> | //apps review <package>')
            return
        service = get_service(aseco)
        if service is not None:
            await service.releases(aseco, admin, name if action != 'updates' else None, review=action == 'review')
        return
    config_apps = _discover_config_apps(aseco)

    if action == 'config':
        if not name:
            await _reply_apps_usage(aseco, login)
            return
        if name in config_apps:
            _show_app_config_window(aseco, admin, name)
            return
        owner = _config_item_owner(aseco, name)
        if owner:
            await _reply(aseco, login, _unknown_apps_target(name))
            return
        await _reply(aseco, login, _unknown_apps_target(name))
        return

    if action == 'reload':
        if not name:
            await _reply_apps_usage(aseco, login)
            return
        if not _can_configure_app(aseco, name):
            await _reply(aseco, login, '{#server}> {#error}App ' + name +
                         ' is not enabled and loaded, or its files are absent. Nothing reloaded.')
            return
        if await _reload_app_runtime(aseco, name):
            _mark_config_pending(aseco, name, False)
            await _refresh_score_preview(aseco, admin)
            await _reply(aseco, login, _reload_done_message(f'app/{name}'))
            return
        if name in config_apps or _is_manageable_standalone_app(aseco, name):
            await _reply(aseco, login, _restart_required_message(f'app/{name}'))
            return
        await _reply(aseco, login, _unknown_apps_target(name))
        return

    if action == 'status':
        if not name:
            await _reply_apps_usage(aseco, login)
            return
        if name in config_apps and name != 'records_dedimania':
            state = _runtime_status(aseco, name, _standalone_loadout_state(aseco, name))
            enabled_count, total = _config_app_counts(aseco, name)
            await _reply(aseco, login, f'{{#server}}> {{#message}}{config_apps[name]["label"]}: '
                         f'{{#highlite}}{state}{{#message}} ({enabled_count}/{total} configured on).')
            return
        if _is_manageable_standalone_app(aseco, name):
            state = _runtime_status(aseco, name, _standalone_loadout_state(aseco, name), _standalone_status(aseco, name))
            await _reply(aseco, login, f'{{#server}}> {{#message}}app/{name}: {{#highlite}}{state}')
            return
        await _reply(aseco, login, _unknown_apps_target(name))
        return

    if action in {'enable', 'disable'}:
        if not name:
            await _reply_apps_usage(aseco, login)
            return
        # Dedimania has editable settings but also supports a service loadout toggle.
        if name in config_apps and name not in MANAGEABLE_STANDALONE_APPS:
            await _reply(aseco, login, '{#server}> {#error}Use {#highlite}/admin apps config ' + name + '{#error} for merged features and UI-owned items.')
            return
        if _is_manageable_standalone_app(aseco, name):
            enabled = action == 'enable'
            app_dir, archived = _standalone_paths(aseco, name)
            if enabled and not app_dir.exists() and archived is not None:
                await _reply(aseco, login, '{#server}> {#error}App is archived in {#highlite}apps/00removed{#error}; use {#highlite}/admin apps add ' + name + '{#error} to restore it first.')
                return
            move_loadout_entry(_apps_toml_path(aseco), f'app/{name}', enabled)
            await _reply(aseco, login, _restart_required_message(f"app/{name} {'enabled' if enabled else 'disabled'} in apps.toml"))
            return
        await _reply(aseco, login, _unknown_apps_target(name))
        return

    if action == 'add':
        if not name:
            await _reply_apps_usage(aseco, login)
            return
        if name in config_apps:
            await _reply(aseco, login, '{#server}> {#error}' + name + ' is a core config app and cannot be added or removed through /admin apps.')
            return
        if name in PROTECTED_STANDALONE_APPS:
            await _reply(aseco, login, '{#server}> {#error}Protected core apps are not managed through /admin apps.')
            return
        app_dir, archived = _standalone_paths(aseco, name)
        if app_dir.exists():
            move_loadout_entry(_apps_toml_path(aseco), f'app/{name}', True)
            await _reply(aseco, login, _restart_required_message(f'app/{name} enabled in apps.toml'))
            return
        if archived is not None:
            _apps_dir(aseco).mkdir(parents=True, exist_ok=True)
            shutil.move(str(archived), str(app_dir))
            move_loadout_entry(_apps_toml_path(aseco), f'app/{name}', True)
            await _reply(aseco, login, _restart_required_message(f'app/{name} restored from apps/00removed and enabled'))
            return
        await _reply(aseco, login, '{#server}> {#error}No install source found for {#highlite}' + name + '{#error}. Expected either {#highlite}apps/' + name + '{#error} or {#highlite}apps/00removed/' + name + '{#error}.')
        return

    if action in {'remove', 'rem'}:
        if not name:
            await _reply_apps_usage(aseco, login)
            return
        if name in config_apps:
            await _reply(aseco, login, '{#server}> {#error}' + name + ' is a core config app and cannot be removed through /admin apps.')
            return
        if name in PROTECTED_STANDALONE_APPS:
            await _reply(aseco, login, '{#server}> {#error}Protected core apps may not be removed through /admin apps.')
            return
        app_dir, archived = _standalone_paths(aseco, name)
        if archived is not None and not app_dir.exists():
            await _reply(aseco, login, '{#server}> {#message}App {#highlite}' + name + '{#message} is already archived in {#highlite}apps/00removed{#message}.')
            return
        if not app_dir.exists():
            await _reply(aseco, login, _unknown_apps_target(name))
            return
        move_loadout_entry(_apps_toml_path(aseco), f'app/{name}', False)
        shutil.move(str(app_dir), str(_archive_destination(aseco, name)))
        await _reply(aseco, login, _restart_required_message(f'app/{name} moved to apps/00removed and disabled'))
        return

    if action in {'fremove', 'frem'}:
        if not name:
            await _reply_apps_usage(aseco, login)
            return
        if len(args) < 3 or str(args[2]).strip().lower() != 'confirm':
            await _reply(aseco, login, '{#server}> {#error}Destructive removal requires confirmation: ' f'{{#highlite}}/admin apps {action} {name} confirm')
            return
        if name in config_apps:
            await _reply(aseco, login, '{#server}> {#error}' + name + ' is a core config app and cannot be physically deleted through /admin apps.')
            return
        if name in PROTECTED_STANDALONE_APPS:
            await _reply(aseco, login, '{#server}> {#error}Protected core apps may not be forcibly removed through /admin apps.')
            return
        app_dir, archived = _standalone_paths(aseco, name)
        target = app_dir if app_dir.exists() else archived
        if target is None or not target.exists():
            await _reply(aseco, login, _unknown_apps_target(name))
            return
        move_loadout_entry(_apps_toml_path(aseco), f'app/{name}', False)
        shutil.rmtree(target)
        await _reply(aseco, login, _restart_required_message(f'app/{name} permanently removed from disk'))
        return

    await _reply_apps_usage(aseco, login)
