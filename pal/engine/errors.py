from __future__ import annotations


class PalError(Exception):
    """Base class for all pal engine errors."""


class EmptyThoughtError(PalError):
    """Raised when add_thought receives empty text."""


class BrainNotInitializedError(PalError):
    """Raised when an operation requires an initialized brain directory."""


class ReadingItemNotFoundError(PalError):
    """Raised when set_status cannot find a reading-list item by id."""


class NotImplementedPhaseError(PalError, NotImplementedError):
    """Raised by engine stubs for capabilities that ship in a later phase."""

    def __init__(self, feature: str, phase: str) -> None:
        self.feature = feature
        self.phase = phase
        super().__init__(f"{feature} is not implemented until Phase {phase}")