"""Hook through which debate prompts include the active operational mode's system prompt.

The debate engine sits below ``aragora.modes``, which holds the operational modes (architect,
reviewer, coder and the custom ones) and their registry, and must not import it. The first
:func:`mode_system_prompt` that finds no provider runs, once per process, the registrations
declared under the ``aragora.debate_mode_prompts`` entry-point group; aragora's own
``pyproject.toml`` declares the mode registry there. A later registration replaces the
previous provider.

:func:`mode_system_prompt` raises :class:`ModePromptProviderNotRegisteredError` when no
provider is registered after that.
"""

from __future__ import annotations

from collections.abc import Callable

from aragora.utils.declared_registrations import DeclaredRegistrations

MODE_PROMPTS_ENTRY_POINT_GROUP = "aragora.debate_mode_prompts"

ModePromptProvider = Callable[[str], "str | None"]
"""Returns the system prompt of the mode named by its argument, or None for an unknown mode."""


class ModePromptProviderNotRegisteredError(RuntimeError):
    """No operational-mode prompt provider is registered."""


_provider: ModePromptProvider | None = None
_declared = DeclaredRegistrations(MODE_PROMPTS_ENTRY_POINT_GROUP)


def register_mode_prompt_provider(provider: ModePromptProvider) -> None:
    """Make ``provider`` supply mode system prompts, replacing any earlier one."""
    global _provider
    _provider = provider


def mode_system_prompt(name: str) -> str | None:
    """The system prompt of the operational mode ``name``, or None when no such mode exists.

    Raises:
        ModePromptProviderNotRegisteredError: no provider is registered, even after the
            declared registrations ran.
    """
    provider = _provider
    if provider is None:
        _declared.load()
        provider = _provider
    if provider is None:
        raise ModePromptProviderNotRegisteredError(
            "no operational-mode prompt provider is registered; import "
            "aragora.cli.mode_prompt_registration and call register_mode_prompts(), or declare "
            f"a registration under the {MODE_PROMPTS_ENTRY_POINT_GROUP!r} entry-point group"
        )
    return provider(name)


__all__ = [
    "MODE_PROMPTS_ENTRY_POINT_GROUP",
    "ModePromptProvider",
    "ModePromptProviderNotRegisteredError",
    "mode_system_prompt",
    "register_mode_prompt_provider",
]
