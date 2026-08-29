"""Expected operational errors and stable process exit codes."""

from __future__ import annotations


class HostmarkError(Exception):
    """Base class for expected user-facing failures."""

    exit_code = 1


class IdentityNotInitializedError(HostmarkError):
    """No local identity file exists."""

    exit_code = 3


class IdentityConflictError(HostmarkError):
    """Both supported local identity files exist."""

    exit_code = 4


class RegistryEntryNotFoundError(HostmarkError):
    """A host selector or local host identity is absent from the registry."""

    exit_code = 5


class HostnameMismatchError(HostmarkError):
    """The operating-system hostname differs from the registry hostname."""

    exit_code = 6


class RetiredHostError(HostmarkError):
    """The selected or local host identity is retired."""

    exit_code = 7


class RegistryValidationError(HostmarkError):
    """Registry bytes or semantics are invalid."""

    exit_code = 8


class NonCanonicalRegistryError(RegistryValidationError):
    """A semantically valid registry is not canonically represented."""


class PrivilegeRequiredError(HostmarkError):
    """The requested identity operation needs elevation."""

    exit_code = 9


class ConcurrentModificationError(HostmarkError):
    """Registry bytes changed during an optimistic transaction."""

    exit_code = 10


class PlatformOperationError(HostmarkError):
    """The current platform or hostname operation is unsupported."""

    exit_code = 11


__all__ = [
    "ConcurrentModificationError",
    "HostmarkError",
    "HostnameMismatchError",
    "IdentityConflictError",
    "IdentityNotInitializedError",
    "NonCanonicalRegistryError",
    "PlatformOperationError",
    "PrivilegeRequiredError",
    "RegistryEntryNotFoundError",
    "RegistryValidationError",
    "RetiredHostError",
]
