"""Group configured FuFi entries without maintaining a second menu tree."""

from apps.platform_ui.navigation import DESTINATIONS


# Match legacy entries by their path, not their caption or their command.
# These moves still work with existing app_defaults.toml files.
PROMOTE = {
    'maps': (
        ('tracks', 'fulllist'),
        ('infomenu', 'trackinfo', 'currenttrackinfo'),
        ('infomenu', 'trackinfo', 'shownext'),
        ('infomenu', 'trackinfo', 'tmxinfo'),
    ),
    'checkpoints': (
        ('records', 'localrecords', 'sectms'),
        ('records', 'dedimania', 'dedisectms'),
        ('custommenu', 'cps'),
        ('custommenu', 'dedicps'),
        ('custommenu', 'cpsspec'),
    ),
    'server': (('infomenu', 'serverinfo', 'serverfullinfo'),),
    'my-ui': (('infomenu', 'personalinfo', 'mysettings'), ('infomenu', 'personalinfo', 'lastwin')),
}
MOVE = {
    'maps': (
        (('tracks',), 'Map filters'),
        (('jukebox',), None),
        (('autojuke',), None),
        (('infomenu', 'trackinfo'), 'Map details'),
    ),
    'server': (
        (('players',), None),
        (('infomenu', 'serverinfo'), 'Server info'),
        (('infomenu', 'personalinfo'), 'My player stats'),
        (('infomenu', 'logsinfo'), None),
        (('infomenu', 'nationsinfo'), None),
        (('votes',), None),
        (('music',), None),
        (('donate',), None),
        (('match',), None),
        (('adminmenu',), None),
        (('jfreu',), None),
        (('infomenu',), None),
    ),
}
ADOPT = {'records': 'records', 'my-ui': 'custommenu'}
_ORIGINAL_SHORTCUT_CAPTIONS = {
    'fulllist': 'All Tracks', 'currenttrackinfo': 'Current Track', 'shownext': 'Next Track',
    'tmxinfo': 'TMX Info', 'sectms': 'Sector Times', 'serverfullinfo': 'Details',
    'mysettings': 'My Settings', 'lastwin': 'Last Window',
}


def _take(entries, path):
    name, *rest = path
    for index, entry in enumerate(entries):
        if entry.unique != name:
            continue
        if not rest:
            return entries.pop(index)
        # Do not move a descendant out of a restricted container.
        if entry.ability or entry.rights:
            return None
        return _take(entry.entries, rest)
    return None


def _has_command(entries, command):
    return any(entry.chatcmd.strip().lower() == command or _has_command(entry.entries, command)
               for entry in entries)


def _append(group, entry):
    if entry is not None:
        entry.parentid = group.id
        group.entries.append(entry)


def _add_root_help(menu, legacy):
    command_list = _take(legacy, ('helpgroup', 'mainhelp'))
    command_help = _take(legacy, ('helpgroup',))
    existing = menu.entries + legacy + ([command_help] if command_help else [])
    if command_list is None and not _has_command(existing, '/helpall'):
        command_list = menu._entry_from_mapping(
            {'caption': 'Command list', 'chatcmd': '/helpall', 'quick': True}, menu.id)
        menu.entries_list.append(command_list)
    if command_list and command_list.caption == 'Main':
        command_list.caption = 'Command list'
    if command_help and command_help.caption == 'Help':
        command_help.caption = 'Command help'
    for entry in (_take(legacy, ('mainhelpsep',)), command_list, command_help):
        _append(menu, entry)


def organize(menu):
    legacy = menu.entries
    promoted = {key: [_take(legacy, path) for path in paths] for key, paths in PROMOTE.items()}
    menu.entries = []
    for key, caption, shortcuts in DESTINATIONS:
        alias = f'quick-{key}'
        adoption = next((entry for entry in legacy if entry.unique == ADOPT.get(key)
                         and not (entry.chatcmd or entry.rights or entry.ability)), None)
        group = _take(legacy, (adoption.unique,)) if adoption else None
        if group is None:
            group = menu._entry_from_mapping({'caption': caption, 'unique': alias}, menu.id)
            menu.entries_list.append(group)
            if key in ADOPT:
                _append(group, _take(legacy, (ADOPT[key],)))
        else:
            group.caption = caption
        menu.destination_entries[alias] = group
        menu.entries.append(group)
        for entry in promoted.get(key, ()):
            _append(group, entry)
        for path, title in MOVE.get(key, ()):
            entry = _take(legacy, path)
            if entry is not None and title:
                entry.caption = title
            _append(group, entry)

        first = []
        for label, command in shortcuts:
            chatcmd = '/' + command
            # Prefer an existing direct entry; keep its ID, checks and attributes.
            existing = next((item for item in group.entries if item.chatcmd.strip().lower() == chatcmd), None)
            if existing is not None:
                group.entries.remove(existing)
                if existing.caption == _ORIGINAL_SHORTCUT_CAPTIONS.get(existing.unique):
                    existing.caption = label
                first.append(existing)
            elif not _has_command(group.entries, chatcmd):
                entry = menu._entry_from_mapping({'caption': label, 'chatcmd': chatcmd, 'quick': True}, group.id)
                menu.entries_list.append(entry)
                first.append(entry)
        group.entries[:0] = first
    _add_root_help(menu, legacy)
    # Custom root entries remain at root. They do not get bundled with built-ins.
    menu.entries.extend(legacy)
