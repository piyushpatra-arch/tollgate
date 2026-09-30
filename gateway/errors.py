"""Errors raised by pipeline stages. Each maps to an HTTP status and an audit outcome."""

from __future__ import annotations


class GatewayError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code  # also used as the audit outcome
        self.message = message
