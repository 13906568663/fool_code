"""Shared metadata types for built-in MCP services."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InternalMcpServiceDefinition:
    """Describes a first-party MCP service owned by this project."""

    name: str
    config_key: str
    display_name: str
    description: str
    package: str
