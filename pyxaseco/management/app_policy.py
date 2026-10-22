"""App-management capabilities shared with the optional in-game manager."""

MANAGEABLE_STANDALONE_APPS = {
    'flexitime': 'FlexiTime', 'bestcps': 'Best CPs', 'bestsecs': 'Best Secs',
    'bestruns': 'Best Runs', 'bestfinishes': 'Best Finishes',
    'best_cp_times': 'Best CP Times', 'records_rpg': 'RPG Records',
    'records_dedimania': 'Dedimania Records',
    'records_trial': 'Trial Records', 'jfreu': 'JFreu', 'ztrack': 'ZTrack',
    'endlesstmxr': 'Endless TMX Random',
}

PROTECTED_STANDALONE_APPS = {
    'admin', 'apps_manager', 'discord', 'help', 'jukebox', 'platform_core',
    'platform_ui', 'players', 'records_dedimania', 'records_local', 'server_info',
    'social_chat', 'tmx', 'ui', 'voting', 'management_bridge',
}

RELOADABLE_APPS = {
    'ui', 'bestcps', 'bestsecs', 'bestruns', 'bestfinishes', 'best_cp_times',
    'checkpoint_tools', 'flexitime', 'endlesstmxr',
}
