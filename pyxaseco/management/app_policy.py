"""App-management capabilities shared with the optional in-game manager."""

MANAGEABLE_STANDALONE_APPS = {
    'server_admin_bridge': 'Server Admin Bridge',
    'match_overlay': 'Match Overlay',
    'pyxa_stats': 'PYXA Stats',
    'alternate_scoretable': 'Alternate Scoretable',
    'server_neighborhood': 'Server Neighborhood',
    'flexitime': 'FlexiTime', 'bestcps': 'Best CPs', 'bestsecs': 'Best Secs',
    'bestruns': 'Best Runs', 'bestfinishes': 'Best Finishes',
    'best_cp_times': 'Best CP Times', 'records_rpg': 'RPG Records',
    'records_dedimania': 'Dedimania Records',
    'records_ultimania': 'Ultimania Records',
    'records_trial': 'Trial Records', 'jfreu': 'JFreu', 'ztrack': 'ZTrack',
    'endlesstmxr': 'Endless TMX Random',
    'seqinfomsg': 'Sequential Info Messages',
    'quotes': 'Quotes', 'cgps': 'Curated GPS', 'hidechat': 'Hide Chat',
    'forcemods': 'ForceMods',
    'serverstats': 'ServerStats',
    'dbtools': 'DBTools',
}

PROTECTED_STANDALONE_APPS = {
    'admin', 'apps_manager', 'discord', 'help', 'jukebox', 'platform_core',
    'platform_ui', 'players', 'records_dedimania', 'records_local', 'server_info',
    'social_chat', 'tmx', 'ui', 'voting', 'management_bridge',
}

RELOADABLE_APPS = {
    'match_overlay',
    'pyxa_stats',
    'alternate_scoretable',
    'server_neighborhood',
    'records_ultimania',
    'ui', 'bestcps', 'bestsecs', 'bestruns', 'bestfinishes', 'best_cp_times',
    'checkpoint_tools', 'flexitime', 'endlesstmxr',
    'seqinfomsg',
    'quotes', 'cgps', 'hidechat',
    'forcemods',
    'serverstats',
    'dbtools',
}
