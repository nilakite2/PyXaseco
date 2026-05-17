"""
Eyepiece handlers package.

This package contains all event, action, and chat handlers
for the records_eyepiece plugin.

Structure:
    events.py   # Server events (onSync, onPlayerConnect, onNewChallenge, etc.)
    actions.py  # ManiaLink actions (onPlayerManialinkPageAnswer)
    chat.py     # Chat commands (/eyepiece, /elist, /estat, /eyeset)
"""

# Intentionally empty to mark this as a package.
# Handlers should be imported explicitly in plugin.py to avoid circular imports.