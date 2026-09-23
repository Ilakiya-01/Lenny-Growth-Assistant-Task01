"""Tool and skill interface for the application agent.

A capability is either *available* (an :class:`AgentTool` implementation the agent
may invoke) or *planned* (a :class:`CapabilityDescriptor` for a pathway that a
later phase implements). The Phase 4 capabilities - transcript search, grounded
Q&A, Ship30for30 and artifact generation - are registered as executable tools by
:func:`default_registry`; the *planned* mechanism stays for capabilities that a
later phase will add, so the router can name a pathway without pretending it can
be executed.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.agent.intents import Intent

logger = logging.getLogger("lenny.agent.tools")


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Outcome of a tool invocation, ready to be merged into agent context."""

    tool: str
    content: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    """Description of a capability, implemented or planned."""

    name: str
    description: str
    intents: tuple[Intent, ...] = ()
    available: bool = False
    phase: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "intents": [intent.value for intent in self.intents],
            "available": self.available,
            "phase": self.phase,
        }


class AgentTool(ABC):
    """A capability the agent can invoke once a later phase implements it."""

    name: ClassVar[str]
    description: ClassVar[str]
    intents: ClassVar[tuple[Intent, ...]] = ()

    @abstractmethod
    async def run(self, arguments: Mapping[str, Any], context: Any) -> ToolResult:
        """Execute the tool for ``arguments`` within the active agent context."""

    def descriptor(self) -> CapabilityDescriptor:
        return CapabilityDescriptor(
            name=self.name,
            description=self.description,
            intents=tuple(self.intents),
            available=True,
        )


class ToolRegistry:
    """Registration and discovery of agent capabilities."""

    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}
        self._planned: dict[str, CapabilityDescriptor] = {}

    def register_tool(self, tool: AgentTool) -> CapabilityDescriptor:
        """Register an executable capability."""
        name = (getattr(tool, "name", "") or "").strip()
        if not name:
            raise ValueError("A registered agent tool needs a non-empty name.")
        if name in self._tools:
            raise ValueError(f"An agent tool named '{name}' is already registered.")
        if name in self._planned and self._planned[name].available:
            raise ValueError(f"An agent capability named '{name}' is already registered.")
        self._tools[name] = tool
        if name in self._planned:
            del self._planned[name]
        logger.debug("Registered agent tool '%s'", name)
        return tool.descriptor()

    def register_planned(self, capability: CapabilityDescriptor) -> CapabilityDescriptor:
        """Register a capability that a later phase implements."""
        name = (capability.name or "").strip()
        if not name:
            raise ValueError("A planned agent capability needs a non-empty name.")
        if name in self._tools:
            raise ValueError(f"An agent capability named '{name}' is already available.")
        self._planned[name] = capability
        return capability

    def tool(self, name: str) -> AgentTool | None:
        return self._tools.get(name)

    def is_available(self, name: str | None) -> bool:
        return bool(name) and name in self._tools

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        """Every known capability, available ones first."""
        available = [tool.descriptor() for _, tool in sorted(self._tools.items())]
        planned = [self._planned[name] for name in sorted(self._planned)]
        return tuple(available + planned)

    def capabilities_for_intent(self, intent: Intent) -> tuple[str, ...]:
        names = [
            name for name, tool in self._tools.items() if intent in tuple(tool.intents)
        ] + [
            name for name, capability in self._planned.items() if intent in capability.intents
        ]
        return tuple(sorted(set(names)))

    def available_capabilities(self) -> tuple[str, ...]:
        return self.names()

    def planned_capabilities(self) -> tuple[str, ...]:
        return tuple(sorted(self._planned))

    def capability_names(self) -> tuple[str, ...]:
        """Every registered capability name, available or planned."""
        return tuple(sorted(set(self._tools) | set(self._planned)))

    def tool_catalog(self) -> Sequence[dict[str, object]]:
        """Minimal tool menu (name + description) for future prompt construction."""
        return [tool.descriptor().to_dict() for _, tool in sorted(self._tools.items())]


def default_registry() -> ToolRegistry:
    """Build the registry with every implemented capability registered.

    The skills import the tool interface from this module, so they are imported
    here rather than at module scope to keep the dependency one-directional.
    """
    from app.agent.skills import DEFAULT_SKILLS

    registry = ToolRegistry()
    for skill in DEFAULT_SKILLS:
        registry.register_tool(skill())
    logger.debug("Default registry ready with tools: %s", ", ".join(registry.names()))
    return registry


__all__ = [
    "AgentTool",
    "CapabilityDescriptor",
    "ToolRegistry",
    "ToolResult",
    "default_registry",
]
