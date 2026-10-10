"""Typed errors. Each carries the CLI exit code it maps to."""
from __future__ import annotations

EXIT_OK = 0
EXIT_INVALID = 2      # invalid input, schema or unsupported version
EXIT_CONFLICT = 3     # ownership conflict or stale generation
EXIT_PROHIBITED = 4   # prohibited by workflow state, authorization or missing prerequisite
EXIT_ENVIRONMENT = 5  # environmental or I/O failure


class CoreError(Exception):
    exit_code = EXIT_ENVIRONMENT

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_json(self) -> dict:
        return {'code': self.code, 'message': self.message, 'details': self.details}


class InvalidInput(CoreError):
    exit_code = EXIT_INVALID


class Conflict(CoreError):
    exit_code = EXIT_CONFLICT


class Prohibited(CoreError):
    exit_code = EXIT_PROHIBITED


class Environment(CoreError):
    exit_code = EXIT_ENVIRONMENT
