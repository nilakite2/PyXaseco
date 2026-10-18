"""Small config edits redraw only their UI owner; full reload stays explicit."""

from .config import _load_config, _state, apply_phase1_defaults, validate_phase1_runtime


BAR_TARGETS = {
    'trackcount_widget': ('trackcount', 'trackcount', 'race'),
    'gamemode_widget': ('gamemode', 'gamemode', 'race'),
    'visitors_widget': ('visitors', 'visitors', 'race'),
    'player_spectator_widget': ('playerspectator', 'player_spectator', 'race'),
    'ladderlimit_widget': ('ladderlimit', 'ladderlimit', 'race'),
    'current_ranking_widget': ('currentranking', 'current_ranking', 'race'),
    'tmexchange_widget': ('tmexchange', 'tmexchange', 'race'),
    'toplist_widget': ('toplist', 'toplist', 'race'),
    'discord_widget': ('discord_widget', 'discord_widget', 'race'),
    'force_play_widget': ('force_play_widget', 'force_play_widget', 'race'),
    'clock_widget': ('clock', 'clock', 'both'),
    'favorite_widget': ('favorite', 'favorite', 'both'),
    'next_environment_widget': ('next_env', 'next_env', 'score'),
    'next_gamemode_widget': ('next_gamemode', 'next_gamemode_widget', 'score'),
    'eyepiece_widget': ('eyepiece_score', 'eyepiece_widget', 'score'),
}


async def reload_ui_item_runtime(aseco, item_key):
    from .handlers import events
    from .widgets import bar_widgets as bars
    root = item_key.split('.')[0]
    if root in ('menu', 'karma', 'banner', 'allbutton'):
        module = __import__('apps.ui.' + root, fromlist=['reload_' + root + '_runtime'])
        await getattr(module, 'reload_' + root + '_runtime')(aseco)
        return
    _load_config(aseco)
    validate_phase1_runtime(aseco)
    apply_phase1_defaults(aseco)
    from pyxaseco.core.widget_delivery import is_score_phase
    if getattr(aseco, 'score_phase', None) is not None:
        _state.challenge_show_next = is_score_phase(aseco)
    _state.warmup = getattr(aseco, 'warmup_phase', False)
    if root in BAR_TARGETS:
        method, attribute, phase = BAR_TARGETS[root]
        cfg = getattr(_state, attribute)
        allowed = phase == 'both' or (_state.challenge_show_next == (phase == 'score'))
        enabled = cfg.score_enabled if root == 'eyepiece_widget' else cfg.enabled
        if not enabled or not allowed:
            await getattr(bars, '_hide_' + method)(aseco)
        elif root == 'favorite_widget':
            await bars._draw_favorite_all(aseco, score=_state.challenge_show_next)
        else:
            await getattr(bars, '_draw_' + method + '_all')(aseco)
        return
    if root == 'challenge_widget':
        _state.last_challenge = {}
        await events._apply_custom_ui_all(aseco)
        await events._draw_challenge_all(aseco)
        return
    record_targets = {
        'local_records': ('player_local_digest', events._draw_local_all),
        'dedimania_records': ('player_dedi_digest', events._draw_dedi_all),
        'live_rankings': ('player_live_digest', events._draw_live_all),
    }
    if root in record_targets:
        digest, redraw = record_targets[root]
        getattr(_state, digest).clear()
        if _state.challenge_show_next and root != 'live_rankings':
            await events._refresh_score_state_records(aseco, 'local' if root == 'local_records' else 'dedi')
        else:
            await redraw(aseco)
        return
    if root == 'checkpointcount_widget':
        await events._draw_cp_all(aseco)
        return
    if root == 'scoretable_lists':
        from .score_data import score_data
        from .toplists import draw_all_score_columns
        from .widgets.score_widgets import draw_all_score_lists
        await score_data(aseco).invalidate(aseco)
        if _state.challenge_show_next:
            await draw_all_score_lists(aseco)
            await draw_all_score_columns(aseco)
        return
    if root == 'round_score':
        from .widgets.score_widgets import draw_round_score
        await draw_round_score(aseco)
        return
    if root == 'custom_ui':
        await events._apply_custom_ui_all(aseco)
        return
    if root in ('donation_widget', 'winning_payout'):
        from .widgets.score_widgets import (
            _broadcast, _empty, ML_DONATION, ML_WINNING_PAYOUT,
            build_donation_widget, build_winning_payout_widget,
        )
        page, build = ((ML_DONATION, build_donation_widget) if root == 'donation_widget'
                       else (ML_WINNING_PAYOUT, build_winning_payout_widget))
        await _broadcast(aseco, build(aseco) if _state.challenge_show_next else _empty(page))
        return
    from .handlers.command_handlers import reload_ui_layout_runtime
    await reload_ui_layout_runtime(aseco)
