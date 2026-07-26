from __future__ import annotations


class EmotionOSError(Exception):
    status_code = 500

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(EmotionOSError):
    status_code = 404


class ValidationError(EmotionOSError):
    status_code = 422


class AudioGenerationError(EmotionOSError):
    status_code = 503


class ProviderConfigurationError(EmotionOSError):
    status_code = 503


class ExternalProviderError(EmotionOSError):
    status_code = 502


class StorageError(EmotionOSError):
    status_code = 400
