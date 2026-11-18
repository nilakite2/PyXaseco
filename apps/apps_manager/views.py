"""ManiaLink views and action IDs for the in-game Apps Manager."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from apps.platform_ui.hud_layout import POSITION_STEPS
from pyxaseco.helpers import display_manialink_multi
from pyxaseco.management.app_policy import MANAGEABLE_STANDALONE_APPS, PROTECTED_STANDALONE_APPS
from .service import (
    _with_config_snapshot, get_service, _root_dir, read_toml,
    _discover_config_apps, _config_items_for_app, _standalone_loadout_state, _standalone_app_names,
    _standalone_status, _runtime_status, _config_item_target_info_from_data, _config_item_state_from_info,
    _config_item_state_text, _display_value, _config_item_summary_from_info, _editable_fields, _editable_fields_from_info,
    _config_app_counts, _ui_config_group_for, _ui_display_label, _config_app_spec, UI_GROUP_ORDER,
    _can_reload_app, _config_save_mode,
)

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


def _apps_action_map(player) -> dict[int, tuple[Any, ...]]:
    action_map = getattr(player, 'apps_action_map', None)
    if not isinstance(action_map, dict):
        action_map = {}
        setattr(player, 'apps_action_map', action_map)
    return action_map


def _reset_apps_action_map(player) -> None:
    setattr(player, 'apps_action_map', {})


def _register_apps_action(player, payload: tuple[Any, ...]) -> int:
    seed = int(getattr(player, 'apps_action_seed', 442000000))
    action_id = seed + 1
    setattr(player, 'apps_action_seed', action_id)
    _apps_action_map(player)[action_id] = payload
    return action_id


def _action_cell(player, label: str, payload: tuple[Any, ...] | None):
    return [label, _register_apps_action(player, payload)] if payload else label


def _score_preview_cell(aseco, admin, item_key='', *, app_key='ui', group=None):
    preview = aseco.get_service('ui/score_preview')
    if not preview or (app_key != 'ui' and not aseco.has_service(f'ui/score_preview/{app_key}')):
        return ''
    payload = ('score_preview', app_key, item_key)
    return _action_cell(admin, 'Stop' if preview.visible(admin, table=app_key == 'alternate_scoretable') else 'Preview',
                        payload if group is None else (*payload, group))


def _preview_scope(aseco, admin, app_key):
    preview = aseco.get_service('ui/score_preview') if app_key == 'ui' else None
    selection = preview.selection(admin) if preview else None
    return selection.config_scope(aseco) if selection else None


def _show_preview_selector(aseco, admin):
    from apps.ui.score_preview import PREVIEW_MODES, PREVIEW_PHASES

    preview = aseco.get_service('ui/score_preview')
    if preview is None:
        return
    selection = preview.selection(admin)
    status = (f'{PREVIEW_PHASES[selection.phase]} / {PREVIEW_MODES[selection.resolved_mode_key(aseco)][1]}'
              if selection else 'Off')
    _reset_apps_action_map(admin)
    rows = [[title, _action_cell(admin, 'Race HUD', ('preview_select', 'ui', 'race', key)),
             _action_cell(admin, 'Score Screen', ('preview_select', 'ui', 'score', key))]
            for key, title in (('current', 'Current server mode'), *((k, title) for k, (_, title) in PREVIEW_MODES.items()))]
    rows.append(['Navigation', _action_cell(admin, 'Back', ('open_config', 'ui')),
                 _action_cell(admin, 'Stop', ('preview_select', 'ui', 'off', 'current')) if selection else ''])
    _show_apps_window(aseco, admin, f'Layout Preview ({status})', ['Icons128x128_1', 'Rankings'],
                      ['Game Mode', 'Race', 'Score'], rows)


def _autosize_widths(
    table_header: list[str],
    entries: list[list[Any]],
    *,
    min_total: float = 1.08,
    max_total: float = 1.38,
) -> list[float]:
    if not table_header:
        return [min_total]

    col_count = len(table_header)
    max_lens = [max(4, len(str(head or ''))) for head in table_header]
    for row in entries:
        for idx in range(min(len(row), col_count)):
            cell = row[idx]
            text = cell[0] if isinstance(cell, list) else cell
            max_lens[idx] = max(max_lens[idx], len(str(text or '')))

    col_widths: list[float] = []
    for idx, length in enumerate(max_lens):
        if idx >= col_count - 2:
            width = 0.12 + min(length, 12) * 0.014
        elif idx == 0:
            width = 0.18 + min(length, 48) * 0.020
        else:
            width = 0.12 + min(length, 40) * 0.015
        col_widths.append(max(0.12, min(width, 1.10)))

    total = sum(col_widths)
    if total < min_total:
        factor = min_total / total if total else 1.0
        col_widths = [width * factor for width in col_widths]
        total = sum(col_widths)
    if total > max_total:
        factor = max_total / total
        col_widths = [width * factor for width in col_widths]
        total = sum(col_widths)

    return [max(min_total, min(total, max_total))] + [round(width, 3) for width in col_widths]


def _show_apps_window(
    aseco: 'Aseco',
    admin,
    header: str,
    icon: list[str | float],
    table_header: list[str],
    entries: list[list[Any]],
    widths: list[float] | None = None,
    *,
    pin_first: bool = False,
) -> None:
    pages = []
    pinned = entries[:1] if pin_first else []
    page = [table_header, *pinned]
    lines = len(pinned)
    for row in entries[len(pinned):]:
        page.append(row)
        lines += 1
        if lines >= 14:
            pages.append(page)
            page = [table_header, *pinned]
            lines = len(pinned)
    if lines > len(pinned) or not pages:
        pages.append(page)

    meta_widths = widths or _autosize_widths(table_header, entries)
    admin.msgs = [[1, header, meta_widths, icon]]
    admin.msgs.extend(pages or [[table_header]])
    display_manialink_multi(aseco, admin)


@_with_config_snapshot
def _show_apps_manager_window(aseco: 'Aseco', admin) -> None:
    _reset_apps_action_map(admin)
    rows: list[list[Any]] = []

    service = get_service(aseco)
    release_state = ('Pending restart' if service and service.restart_needed else
                     'Downloaded, not installed' if service and 'downloaded' in service.package_states.values() else '')
    rows.append(['Verified Releases', 'Packages', release_state,
                 _action_cell(admin, 'Check', ('check_releases',)), '', ''])

    rows.append(['{#highlite}Configurable App Homes', '', '', '', '', ''])
    config_apps = list(_discover_config_apps(aseco).items())
    config_apps.sort(key=lambda pair: (0 if _standalone_loadout_state(aseco, pair[0]) != 'disabled' else 1, pair[1]['label'].lower()))
    for app_key, spec in config_apps:
        loadout_state = _standalone_loadout_state(aseco, app_key)
        if loadout_state == 'disabled':
            state_text = 'disabled'
        else:
            enabled, total = _config_app_counts(aseco, app_key)
            state_text = f'{enabled}/{total} on'
        rows.append([
            spec['label'],
            'Config',
            _runtime_status(aseco, app_key, loadout_state) + (' | ' + state_text if loadout_state != 'disabled' else ''),
            _action_cell(admin, 'Config', ('open_config', app_key)),
            '',
            _action_cell(admin, 'Reload', ('reload_app', app_key)) if _can_reload_app(aseco, app_key) else '',
        ])

    while rows and (len(rows) % 14) != 0:
        rows.append(['', '', '', '', '', ''])

    rows.append(['{#highlite}Standalone Optional Apps', '', '', '', '', ''])
    standalone_names = list(_standalone_app_names())
    standalone_names.sort(key=lambda name: (0 if _standalone_loadout_state(aseco, name) != 'disabled' else 1, MANAGEABLE_STANDALONE_APPS.get(name, name).lower()))
    for app_name in standalone_names:
        label = MANAGEABLE_STANDALONE_APPS.get(app_name, app_name)
        status = _standalone_status(aseco, app_name)
        primary = ''
        secondary = ''
        if status == 'enabled':
            primary = _action_cell(admin, 'Disable', ('toggle_app', 'disable', app_name))
            if app_name not in PROTECTED_STANDALONE_APPS:
                secondary = _action_cell(admin, 'Remove', ('archive_app', app_name))
        elif status == 'disabled':
            primary = _action_cell(admin, 'Enable', ('toggle_app', 'enable', app_name))
            if app_name not in PROTECTED_STANDALONE_APPS:
                secondary = _action_cell(admin, 'Remove', ('archive_app', app_name))
        elif status == 'removed' and app_name not in PROTECTED_STANDALONE_APPS:
            primary = _action_cell(admin, 'Add', ('restore_app', app_name))
        rows.append([
            label,
            'App',
            _runtime_status(aseco, app_name, _standalone_loadout_state(aseco, app_name), status),
            primary,
            secondary,
            _action_cell(admin, 'Reload', ('reload_app', app_name)) if _can_reload_app(aseco, app_name) else '',
        ])

    _show_apps_window(
        aseco,
        admin,
        'Apps Manager',
        ['Icons128x128_1', 'Buddies'],
        ['Name', 'Type', 'State', 'Primary', 'Secondary', 'Reload'],
        rows,
    )


def _show_release_window(aseco, admin, catalogue):
    from pyxaseco.core.aseco import PYXASECO_VERSION
    from pyxaseco.management.release_manifest import compatibility
    _reset_apps_action_map(admin)
    service = get_service(aseco)
    rows = [['Nothing is installed or restarted by this window.', '', '', '', '', '']]
    for package in catalogue['packages']:
        reasons = compatibility(package, PYXASECO_VERSION, '.'.join(map(str, sys.version_info[:3])))
        dependencies = len(package['requires_apps']) + len(package['python_requirements'])
        identity = package['id']
        local = service.package_states.get(identity) if service else None
        state = ('Pending restart' if service and identity in service.pending_packages else
                 'Downloaded, not installed' if local == 'downloaded' else
                 'Installed' if local == 'installed' else 'Incompatible' if reasons else 'Verified')
        rows.append([identity, package['version'], state,
                     _action_cell(admin, 'Download', ('stage_release', identity)) if not reasons and local != 'downloaded' else '',
                     _action_cell(admin, 'Review', ('review_release', identity)) if local in {'downloaded', 'installed'} and not reasons else '',
                     '; '.join(reasons) if reasons else str(dependencies) + ' requirements'])
    rows.append(['Recheck publishers', '', '', _action_cell(admin, 'Check', ('check_releases',)), '', ''])
    _show_apps_window(aseco, admin, 'Verified Releases', ['Icons128x128_1', 'LoadTrack'],
                      ['Package', 'Version', 'State', 'Download', 'Preview', 'Compatibility'], rows)


def _show_package_review_window(aseco, admin, plan, *, confirm=False):
    _reset_apps_action_map(admin)
    from collections import Counter
    counts = Counter(item['action'] for item in plan['files'])
    added = counts['add']
    replaced = counts['replace'] + counts['force_replace']
    removed = counts['remove'] + counts['force_remove']
    rows = [
        ['What will change', plan['version'], f'{added} added, {replaced} replaced, {removed} removed ({plan["package"]}).'],
        ['What stays', 'Preserved', f'{counts["preserve_config"]} configs, {counts["keep_modified"]} modified files, and instance data.'],
        ['Next step', 'Manual', 'Meet requirements below.' if plan.get('requirements') else
         'Confirm to copy. Run //pyres yourself afterwards.' if confirm else 'Review files, then Apply. Restart is manual.'],
        ['Optional apps', 'Unchanged', 'Missing optional apps are not added by controller updates.'],
    ]
    for requirement in plan.get('requirements', []):
        rows.append(['Before copying', 'Owner action', requirement])
    payload = ('apply_release' if confirm else 'confirm_release', plan['package'], plan['review'], plan['force'])
    if plan.get('requirements'):
        rows.append(['Requirements not met', 'No files copied', 'Use the existing Python; then review again.'])
    elif confirm:
        rows.append(['Confirm file replacement', '', _action_cell(admin, 'Confirm', payload)])
        rows.append(['Modified official code', 'Replaced' if plan['force'] else 'Kept', 'Existing configuration is always preserved.'])
    else:
        rows.append(['Copy reviewed files', '', _action_cell(admin, 'Apply...', payload)])
        if not plan['force']:
            rows.append(['Also replace modified code', '', _action_cell(admin, 'Force Replace...', ('force_review', plan['package']))])
    rows.append(['Recheck publishers', '', _action_cell(admin, 'Packages', ('check_releases',))])
    for item in plan['files']:
        if item['action'] != 'unchanged':
            detail = ('Left in place' if item['action'] in {'keep_modified', 'preserve_config'} else
                      'New release file' if item['action'] == 'add' else 'Backed up before change')
            rows.append([item['file'], item['action'].replace('_', ' '), detail])
    admin._release_review = plan
    _show_apps_window(aseco, admin, 'Confirm Update' if confirm else 'Update Review', ['Icons128x128_1', 'LoadTrack'],
                     ['File / Item', 'Change / State', 'Details'], rows, widths=[1.38, 0.58, 0.18, 0.62])


@_with_config_snapshot
def _show_app_config_window(aseco: 'Aseco', admin, app_key: str, group: str | None = None) -> None:
    spec = _discover_config_apps(aseco).get(app_key)
    if not spec:
        return

    _reset_apps_action_map(admin)
    rows: list[list[Any]] = []
    items = _config_items_for_app(aseco, app_key)
    scope = _preview_scope(aseco, admin, app_key)
    target = ()
    if scope:
        scope_mode, scope_phase = scope
        target = (scope,)
        items = [item for item in items if '.gamemode.' not in item['key'] or
                 item['key'].split('.gamemode.', 1)[1].split('.')[0] in (
                     {scope_mode, 'score'} if scope_phase == 'score' else {scope_mode})]
    icon = ['Icons128x128_1', 'ProfileAdvanced']
    if app_key == 'ui':
        icon = ['Icons128x128_1', 'Buddies']
        if group not in UI_GROUP_ORDER:
            counts = dict.fromkeys(UI_GROUP_ORDER, 0)
            for item in items:
                counts[_ui_config_group_for(item['key'])] += 1
            rows = [[name, str(counts[name]), _action_cell(admin, 'Open', ('open_config', 'ui', name))]
                    for name in UI_GROUP_ORDER]
            rows.append(['Score Screen Preview', 'Sample data', _score_preview_cell(aseco, admin)])
            if aseco.has_service('ui/score_preview'):
                rows.append(['Layout Preview', 'Race / Score', _action_cell(admin, 'Choose', ('preview_menu', 'ui'))])
            rows.append(['Apps Manager', '', _action_cell(admin, 'Back', ('apps_home',))])
            _show_apps_window(aseco, admin, f'{spec["label"]} Config', icon,
                              ['Section', 'Items', 'Action'], rows)
            return
        items = sorted((item for item in items if _ui_config_group_for(item['key']) == group),
                       key=lambda item: item['label'])
        rows.append(['{#highlite}Navigation', '', '', _action_cell(admin, 'Back', ('open_config', 'ui')),
                     '', _score_preview_cell(aseco, admin, group=group)])
    elif preview := _score_preview_cell(aseco, admin, app_key=app_key):
        rows.append(['{#highlite}Score Screen Preview', '', '', preview, '', ''])
    for item in items:
        file_path = _root_dir(aseco) / item['file']
        data = read_toml(file_path)
        info = _config_item_target_info_from_data(aseco, item, data, file_path=file_path, scope=scope)
        state = _config_item_state_from_info(item, info)
        summary = _config_item_summary_from_info(aseco, item, info)
        editable = _editable_fields_from_info(aseco, item, info)
        rows.append([
            _ui_display_label(item) if app_key == 'ui' else item['label'],
            _config_item_state_text(state),
            summary,
            _action_cell(admin, 'Edit', ('open_edit', app_key, item['key'])) if editable else '',
            _action_cell(admin, 'Enable', ('toggle_config', app_key, item['key'], True, *target)) if state not in {'enabled', 'config', 'missing'} else '',
            _action_cell(admin, 'Disable', ('toggle_config', app_key, item['key'], False, *target)) if state not in {'disabled', 'config', 'missing'} else '',
        ])

    if app_key == 'platform_ui' and _config_save_mode(aseco, app_key, 'panels.admin') == 'reload':
        save_note = 'Panel positions apply live'
    else:
        save_note = 'Saved and reloaded' if _config_save_mode(aseco, app_key) == 'reload' else 'Saved. Restart required'
    widths = None
    if app_key == 'ui':
        widths = [1.38, 0.34, 0.16, 0.40, 0.12, 0.18, 0.18]
    _show_apps_window(
        aseco,
        admin,
        f'{group or spec["label"] + " Config"} ({save_note})',
        icon,
        ['Item', 'State', 'Summary', 'Edit', 'Enable', 'Disable'],
        rows,
        widths=widths,
        pin_first=app_key == 'ui' and group in UI_GROUP_ORDER,
    )


@_with_config_snapshot
def _show_item_edit_window(aseco: 'Aseco', admin, app_key: str, item_key: str) -> None:
    item = next((entry for entry in _config_items_for_app(aseco, app_key) if entry['key'] == item_key), None)
    if not item:
        return

    _reset_apps_action_map(admin)
    scope = _preview_scope(aseco, admin, app_key)
    fields = _editable_fields(aseco, item, scope=scope)
    action = ('adjust_field', app_key, item_key)
    target = (scope,) if scope else ()
    preview = _score_preview_cell(aseco, admin, item_key, app_key=app_key)
    back = ('open_config', app_key, _ui_config_group_for(item_key)) if app_key == 'ui' else ('open_config', app_key)
    rows: list[list[Any]] = [[
        '{#highlite}Navigation',
        '',
        preview,
        '',
        '',
        '',
        '',
        _action_cell(admin, 'Back', back),
    ]]

    for field in fields:
        label = str(field.get('label') or field.get('field_key') or '')
        value = _display_value(field.get('value'))
        if field.get('kind') == 'bool':
            rows.append([
                label,
                value,
                '',
                '',
                _action_cell(admin, 'Off', (*action, field['field_key'], -1.0, *target)),
                _action_cell(admin, 'On', (*action, field['field_key'], 1.0, *target)),
                '',
                '',
            ])
        elif field.get('geometry'):
            axis = field['axis']
            negative, positive = ('Left', 'Right') if axis == 'x' else ('Down', 'Up') if axis == 'y' else ('-', '+')
            separator = ' ' if axis else ''
            steps = tuple(-step for step in reversed(POSITION_STEPS)) + POSITION_STEPS
            cells = [
                _action_cell(
                    admin, f'{negative if step < 0 else positive}{separator}{abs(step):g}',
                    (*action, field['field_key'], step, *target),
                )
                for step in steps
            ]
            rows.append([label, value, *cells])
        else:
            neg_big = _display_value(-float(field['step_big']))
            neg_def = _display_value(-1.0)
            neg_small = _display_value(-float(field['step_small']))
            pos_small = _display_value(float(field['step_small']))
            pos_def = _display_value(1.0)
            pos_big = _display_value(float(field['step_big']))
            rows.append([
                label,
                value,
                _action_cell(admin, neg_big, (*action, field['field_key'], -float(field['step_big']), *target)),
                _action_cell(admin, neg_def, (*action, field['field_key'], -1.0, *target)),
                _action_cell(admin, neg_small, (*action, field['field_key'], -float(field['step_small']), *target)),
                _action_cell(admin, f'+{pos_small}', (*action, field['field_key'], float(field['step_small']), *target)),
                _action_cell(admin, f'+{pos_def}', (*action, field['field_key'], 1.0, *target)),
                _action_cell(admin, f'+{pos_big}', (*action, field['field_key'], float(field['step_big']), *target)),
            ])

    title = f'{_config_app_spec(aseco, app_key)["label"]}: {item["label"]}'
    if scope:
        from apps.ui.score_preview import PREVIEW_MODES
        title += ' | ' + PREVIEW_MODES[scope[0]][1]
    _show_apps_window(
        aseco,
        admin,
        title,
        ['Icons128x128_1', 'ProfileAdvanced'],
        ['Field', 'Value', 'Large', 'Normal', 'Fine', 'Fine', 'Normal', 'Large'],
        rows,
        widths=([1.65, 0.29, 0.12, 0.19, 0.18, 0.20, 0.20, 0.18, 0.19]
                if any(field.get('axis') for field in fields)
                else [1.34, 0.24, 0.18, 0.14, 0.14, 0.14, 0.14, 0.18, 0.18]),
        pin_first=app_key == 'ui',
    )
