"""The email recipient record shared by notification senders.

:mod:`aragora.integrations.email` sends to it and re-exports it; lower packages such
as the knowledge mound build recipients from here without importing the integrations
package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EmailRecipient:
    """An email recipient."""

    email: str
    name: str | None = None
    preferences: dict[str, Any] = field(default_factory=dict)

    @property
    def formatted(self) -> str:
        """Get formatted email address."""
        if self.name:
            return f"{self.name} <{self.email}>"
        return self.email


__all__ = ["EmailRecipient"]
