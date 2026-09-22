"""
UI handlers package.

This package contains the event, action, and command handlers
for the shared UI app.

Structure:
    events.py            # Server events (onSync, onPlayerConnect, onNewChallenge, etc.)
    actions.py           # ManiaLink actions (onPlayerManialinkPageAnswer)
    command_handlers.py  # Chat commands (/eyepiece, /elist, /estat, /eyeset)
"""

# Intentionally empty to mark this as a package.
# Handlers should be imported explicitly in app.py to avoid circular imports.
