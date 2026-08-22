"""Service-layer errors.

The service modules raise these instead of fastapi.HTTPException so they stay
free of web-framework imports and can be called from anywhere.

main.py registers handlers that render them with the same status codes and the
same {"detail": ...} body FastAPI produced before the extraction, so no client
sees a difference.
"""

from __future__ import annotations


class ServiceError(Exception):
    """Base class for errors the API layer knows how to translate."""

    status_code = 500

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ResourceNotFound(ServiceError):
    """
    The row does not exist, or it belongs to someone else.

    Those two cases are deliberately indistinguishable: reporting them
    differently would let a caller enumerate other users' topic ids.
    """

    status_code = 404


class OperationFailed(ServiceError):
    """A write was rejected — bad input, constraint violation."""

    status_code = 400


class TooManyRequests(ServiceError):
    """The caller is being rate limited and should retry later."""

    status_code = 429
