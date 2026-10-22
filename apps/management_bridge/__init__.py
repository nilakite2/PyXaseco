"""Optional local management bridge; importing does not open a listener."""

from .app import APP_METADATA, register

__all__ = ['APP_METADATA', 'register']
