"""Tool/skill interface and registry tests.

Phase 4 implements the capabilities behind the specialized pathways, so the
default registry now exposes four runnable tools. The *planned* mechanism stays
part of the interface - a later phase can announce a pathway before it can run -
which is why the registry tests below still exercise it.
"""

from __future__ import annotations

import pytest

from app.agent.intents import Intent
from app.agent.tools import AgentTool, CapabilityDescriptor, ToolRegistry, ToolResult, default_registry

PHASE_4_CAPABILITIES = ("artifact_generator", "ship30for30", "transcript_qa", "transcript_search")


class EchoTool(AgentTool):
    """Minimal executable capability used to prove the interface works."""

    name = "echo"
    description = "Return the supplied text."
    intents = (Intent.GENERAL,)

    def __init__(self) -> None:
        self.invocations: list[dict] = []

    async def run(self, arguments, context) -> ToolResult:
        self.invocations.append({"arguments": dict(arguments), "context": context})
        return ToolResult(tool=self.name, content=str(arguments.get("text", "")), metadata={"echoed": True})


def test_default_registry_exposes_the_phase_4_capabilities_as_executable() -> None:
    registry = default_registry()

    assert registry.available_capabilities() == PHASE_4_CAPABILITIES
    assert registry.planned_capabilities() == ()
    assert registry.capability_names() == PHASE_4_CAPABILITIES
    assert all(registry.is_available(name) is True for name in PHASE_4_CAPABILITIES)


def test_shipped_descriptors_name_their_intent_and_are_available() -> None:
    descriptors = {descriptor.name: descriptor for descriptor in default_registry().descriptors()}

    assert descriptors["transcript_search"].intents == (Intent.RAG_QA,)
    assert descriptors["transcript_qa"].intents == (Intent.RAG_QA,)
    assert descriptors["ship30for30"].intents == (Intent.SHIP30FOR30,)
    assert descriptors["artifact_generator"].intents == (Intent.ARTIFACT_GENERATION,)
    assert all(descriptor.available is True for descriptor in descriptors.values())
    assert all(descriptor.phase is None for descriptor in descriptors.values())


def test_shipped_capabilities_expose_an_executable_tool() -> None:
    registry = default_registry()

    for name in PHASE_4_CAPABILITIES:
        tool = registry.tool(name)
        assert isinstance(tool, AgentTool)
        assert tool.descriptor().to_dict() == {
            "name": name,
            "description": tool.description,
            "intents": [intent.value for intent in tool.intents],
            "available": True,
            "phase": None,
        }


def test_a_tool_can_be_registered_and_discovered(run_async) -> None:
    registry = ToolRegistry()
    tool = EchoTool()

    descriptor = registry.register_tool(tool)

    assert descriptor.name == "echo"
    assert descriptor.available is True
    assert registry.is_available("echo") is True
    assert registry.names() == ("echo",)
    assert registry.tool("echo") is tool
    assert registry.capabilities_for_intent(Intent.GENERAL) == ("echo",)
    assert registry.tool_catalog() == [
        {"name": "echo", "description": "Return the supplied text.", "intents": ["general"], "available": True, "phase": None}
    ]

    result = run_async(tool.run({"text": "hi"}, context=None))
    assert result.tool == "echo"
    assert result.content == "hi"
    assert result.metadata == {"echoed": True}
    assert tool.invocations[0]["arguments"] == {"text": "hi"}


def test_registering_a_tool_promotes_a_planned_capability() -> None:
    registry = ToolRegistry()
    registry.register_planned(CapabilityDescriptor(name="echo", description="planned"))

    registry.register_tool(EchoTool())

    assert registry.is_available("echo") is True
    assert registry.planned_capabilities() == ()
    assert [descriptor.name for descriptor in registry.descriptors()] == ["echo"]


def test_available_descriptors_are_listed_before_planned_ones() -> None:
    registry = ToolRegistry()
    registry.register_planned(CapabilityDescriptor(name="zz_planned", description="not implemented yet"))
    registry.register_tool(EchoTool())

    names = [descriptor.name for descriptor in registry.descriptors()]
    assert names == ["echo", "zz_planned"]


def test_duplicate_registration_is_rejected() -> None:
    registry = ToolRegistry()
    registry.register_tool(EchoTool())

    with pytest.raises(ValueError):
        registry.register_tool(EchoTool())

    with pytest.raises(ValueError):
        registry.register_planned(CapabilityDescriptor(name="echo", description="already available"))


def test_unnamed_capabilities_are_rejected() -> None:
    registry = ToolRegistry()

    with pytest.raises(ValueError):
        registry.register_planned(CapabilityDescriptor(name="  ", description="nameless"))
    with pytest.raises(ValueError):
        registry.register_tool(NamelessTool())


def test_capabilities_for_an_intent_are_merged_and_deduplicated() -> None:
    registry = default_registry()
    registry.register_planned(
        CapabilityDescriptor(name="transcript_summarizer", description="planned too", intents=(Intent.RAG_QA,))
    )

    assert registry.capabilities_for_intent(Intent.RAG_QA) == (
        "transcript_qa",
        "transcript_search",
        "transcript_summarizer",
    )
    assert registry.capabilities_for_intent(Intent.SHIP30FOR30) == ("ship30for30",)
    assert registry.capabilities_for_intent(Intent.GENERAL) == ()


def test_capability_descriptor_serializes_to_plain_data() -> None:
    descriptor = CapabilityDescriptor(
        name="transcript_search",
        description="Semantic search over transcript chunks.",
        intents=(Intent.RAG_QA,),
        available=False,
        phase=4,
    )

    assert descriptor.to_dict() == {
        "name": "transcript_search",
        "description": "Semantic search over transcript chunks.",
        "intents": ["rag_qa"],
        "available": False,
        "phase": 4,
    }


class NamelessTool(AgentTool):
    name = ""
    description = "No name."

    async def run(self, arguments, context) -> ToolResult:  # pragma: no cover - never invoked
        return ToolResult(tool=self.name, content="")
