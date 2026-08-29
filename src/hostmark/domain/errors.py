from __future__ import annotations


class HostmarkError(Exception):
    """Base class for expected user-facing failures."""

    exit_code = 1


class IdentityNotInitializedError(HostmarkError):
    exit_code = 3


class IdentityConflictError(HostmarkError):
    exit_code = 4


class RegistryEntryNotFoundError(HostmarkError):
    exit_code = 5


class HostnameMismatchError(HostmarkError):
    exit_code = 6


class RetiredHostError(HostmarkError):
    exit_code = 7


class RegistryValidationError(HostmarkError):
    exit_code = 8


class NonCanonicalRegistryError(RegistryValidationError):
    pass


class PrivilegeRequiredError(HostmarkError):
    exit_code = 9


class ConcurrentModificationError(HostmarkError):
    exit_code = 10


class PlatformOperationError(HostmarkError):
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
