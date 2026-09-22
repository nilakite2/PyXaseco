"""Compatibility shim for the challenge widget now owned by records_eyepiece."""

from apps.ui import challenge_widget as _impl

globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})
__all__ = [k for k in globals() if not k.startswith("__")]
