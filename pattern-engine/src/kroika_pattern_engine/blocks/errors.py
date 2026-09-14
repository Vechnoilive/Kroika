"""Stable, user-facing failures for experimental base-block construction."""

from __future__ import annotations


class BlockConstructionError(ValueError):
    """A request is outside the explicitly implemented block domain."""

    def __init__(self, code: str, message_ru: str, json_pointer: str = "/"):
        self.code = code
        self.message_ru = message_ru
        self.json_pointer = json_pointer
        super().__init__(f"{code} {json_pointer}: {message_ru}")
