class CtxError(Exception):
    """Base exception for ctx."""


class ConfigError(CtxError):
    """Raised when ledger configuration cannot be loaded or validated."""

