"""Thin tracklist entry point for the TMX app."""

from apps.tmx import tracklist as _impl

globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})
__all__ = [k for k in globals() if not k.startswith("__")]
