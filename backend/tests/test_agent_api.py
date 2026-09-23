"""API tests for the development-only agent verification endpoints.

These endpoints exist to verify the Phase 3-4 architecture end to end. They are
not the production chat API and must not be registered in production.
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.agent.agent import ApplicationAgent
from app.agent.skills.artifacts import ARTIFACT_TYPE_MARKDOWN
from app.agent.skills.grounded_qa import MISSING_EVIDENCE_REPLY
from app.api import dev_agent
from app.config import Settings, get_settings
from app.errors import LLMConfigurationError, TranscriptSearchError
from app.llm.factory import MODE_OLLAMA

CAPABILITIES_URL = "/api/dev/agent/capabilities"
ROUTE_URL = "/api/dev/agent/route"
RESPOND_URL = "/api/dev/agent/respond"
SEARCH_URL = "/api/dev/agent/search"

ROUTING_EXAMPLES = [
    ("What did Lenny's guests say about product-market fit?", "rag_qa", "transcript_search"),
    ("Write a 1250-word essay about finding product-market fit.", "ship30for30", "ship30for30"),
    ("Create a markdown product strategy document from this discussion.", "artifact_generation", "artifact_generation"),
    ("Hello, how are you?", "general", "direct_response"),
]

#: Provider reply for the artifact pathway: the documented Phase 4 schema.
ARTIFACT_JSON = json.dumps(
    {
        "type": "markdown",
        "title": "Product strategy",
        "content": "# Product strategy\n\nShip the retention fix first.",
    }
)

WRITING_REPLY = (
    "# Retention before acquisition\n\n"
    "Most growth advice starts in the wrong place.\n\n"
    "## Fix churn first\n\n"
    "- Measure churn weekly\n"
    "- Talk to churned users\n"
    "- Fix the top reason\n\n"
    "**Retention is the compounding asset** that makes every later channel work.\n\n"
    "## The takeaway\n\nEarn the right to grow."
)


@pytest.fixture
def stub_agent(monkeypatch, scripted_client):
    """Replace the cached agent with one whose provider is scripted."""
    built: dict = {}

    def _install(text: str = "Hello! How can I help?", error: Exception | None = None) -> ApplicationAgent:
        agent = ApplicationAgent(client=scripted_client(text=text, error=error), llm_mode=MODE_OLLAMA)
        built["agent"] = agent
        monkeypatch.setattr(dev_agent, "get_application_agent", lambda: agent)
        return agent

    return _install


def test_capabilities_endpoint_reports_the_implemented_capabilities(client: TestClient) -> None:
    response = client.get(CAPABILITIES_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["providers"] == ["anthropic", "ollama"]
    assert body["llm_mode"] in {"cloud", "ollama"}
    assert body["available_tools"] == [
        "artifact_generator",
        "ship30for30",
        "transcript_qa",
        "transcript_search",
    ]
    assert [capability["name"] for capability in body["capabilities"]] == body["available_tools"]
    assert all(capability["available"] is True for capability in body["capabilities"])
    assert all(capability["phase"] is None for capability in body["capabilities"])


@pytest.mark.parametrize(("message", "intent", "execution_path"), ROUTING_EXAMPLES)
def test_route_endpoint_classifies_without_a_provider(client: TestClient, message, intent, execution_path) -> None:
    response = client.post(ROUTE_URL, json={"message": message})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == intent
    assert body["execution_path"] == execution_path
    assert body["classifier"] == "heuristic"
    assert isinstance(body["confidence"], float)
    assert "prompt" not in body
    assert "reasoning" not in body


def test_route_endpoint_reports_capability_availability(client: TestClient) -> None:
    response = client.post(ROUTE_URL, json={"message": "What did Lenny's guests say about churn?"})

    body = response.json()
    assert body["capability"] == "transcript_qa"
    assert body["capability_available"] is True


def test_route_endpoint_accepts_a_general_request(client: TestClient) -> None:
    body = client.post(ROUTE_URL, json={"message": "Hello, how are you?"}).json()

    assert body["capability"] is None
    assert body["capability_available"] is True


@pytest.mark.parametrize("payload", [{}, {"message": ""}])
def test_route_endpoint_rejects_missing_or_empty_messages(client: TestClient, payload) -> None:
    assert client.post(ROUTE_URL, json=payload).status_code == 422


def test_respond_endpoint_returns_a_structured_result(client: TestClient, stub_agent) -> None:
    stub_agent(text="Product-market fit is when the market pulls the product.")

    response = client.post(RESPOND_URL, json={"message": "Hello, how are you?"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["intent"] == "general"
    assert body["execution_path"] == "direct_response"
    assert body["reply"] == "Product-market fit is when the market pulls the product."
    assert body["llm_mode"] == MODE_OLLAMA
    assert body["provider"] == "fake"
    assert body["usage"]["total_tokens"] == 2
    assert [event["stage"] for event in body["activity"]][-1] == "completed"
    assert "Hello, how are you?" not in str(body["activity"])


def test_respond_endpoint_executes_the_writing_capability(client: TestClient, stub_agent) -> None:
    agent = stub_agent(text=WRITING_REPLY)

    response = client.post(RESPOND_URL, json={"message": "Write a 1250-word essay about retention."})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["intent"] == "ship30for30"
    assert body["capability"] == "ship30for30"
    assert body["capability_available"] is True
    assert body["reply"] == WRITING_REPLY
    assert body["skills"] == ["ship30for30"]
    assert body["artifact"] is None
    assert body["metadata"]["word_count"] > 0
    assert body["metadata"]["reading_time_minutes"] >= 1
    assert "executing_capability" in [event["stage"] for event in body["activity"]]
    assert len(agent.client.calls) == 1


def test_respond_endpoint_returns_a_structured_artifact(client: TestClient, stub_agent) -> None:
    stub_agent(text=ARTIFACT_JSON)

    response = client.post(RESPOND_URL, json={"message": "Create a markdown product strategy document."})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "artifact_generation"
    assert body["artifact"] == {
        "type": ARTIFACT_TYPE_MARKDOWN,
        "title": "Product strategy",
        "content": "# Product strategy\n\nShip the retention fix first.",
        "css": None,
    }
    # The artifact body travels as structured data, never inside the assistant text.
    assert body["reply"] is not None
    assert "# Product strategy" not in body["reply"]
    assert body["metadata"]["artifact_type"] == ARTIFACT_TYPE_MARKDOWN
    assert "generating_response" not in [event["stage"] for event in body["activity"]]


def test_respond_endpoint_grounds_a_question_in_retrieved_evidence(
    client: TestClient, stub_agent, fake_retrieval, transcript_result
) -> None:
    fake_retrieval.script(
        transcript_result(chunk_index=0, similarity=0.81),
        transcript_result(chunk_index=3, content="Pricing follows the value you already deliver.", similarity=0.73),
    )
    agent = stub_agent(text="Ada Lovelace argues retention compounds before acquisition.")

    response = client.post(RESPOND_URL, json={"message": "What did Lenny's guests say about retention?"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "rag_qa"
    assert body["capability"] == "transcript_qa"
    assert body["reply"] == "Ada Lovelace argues retention compounds before acquisition."
    assert body["skills"] == ["transcript_qa"]
    assert body["metadata"]["grounded"] is True
    assert body["metadata"]["evidence_count"] == 2
    assert [source["episode_id"] for source in body["sources"]] == ["pytest-episode", "pytest-episode"]
    assert body["sources"][0]["title"] == "Growth loops that compound"
    assert body["sources"][0]["guest"] == "Ada Lovelace"
    assert body["sources"][0]["youtube_url"].startswith("https://www.youtube.com/watch")
    assert body["sources"][0]["publish_date"] == "2024-05-01"

    prompt = agent.client.calls[0]["messages"][0].content
    assert "Retention compounds" in prompt
    assert "Pricing follows the value" in prompt
    assert "retrieving_evidence" in [event["stage"] for event in body["activity"]]


def test_respond_endpoint_states_insufficient_evidence_instead_of_guessing(
    client: TestClient, stub_agent, fake_retrieval
) -> None:
    fake_retrieval.script()
    agent = stub_agent(text="A confident answer invented from general knowledge.")

    response = client.post(RESPOND_URL, json={"message": "What did Lenny's guests say about nuclear fusion?"})

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == MISSING_EVIDENCE_REPLY
    assert body["metadata"]["insufficient_evidence"] is True
    assert body["metadata"]["grounded"] is False
    assert body["sources"] == []
    assert agent.client.calls == []


def test_respond_endpoint_reports_a_capability_failure_without_internals(client: TestClient, stub_agent) -> None:
    stub_agent(text="This is not the JSON artifact that was requested.")

    response = client.post(RESPOND_URL, json={"message": "Create a markdown product strategy document."})

    assert response.status_code == 502
    assert "Traceback" not in response.text
    assert "This is not the JSON artifact" not in response.text
    assert response.json()["detail"] == (
        "The model did not return a valid artifact structure. Try rephrasing the request "
        "or asking for a simpler artifact."
    )


def test_search_endpoint_returns_retrieved_passages(client: TestClient, fake_retrieval, transcript_result) -> None:
    fake_retrieval.script(transcript_result(similarity=0.77))

    response = client.post(SEARCH_URL, json={"query": "retention compounds", "top_k": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "retention compounds"
    assert body["result_count"] == 1
    assert body["results"][0]["episode_id"] == "pytest-episode"
    assert body["results"][0]["title"] == "Growth loops that compound"
    assert body["results"][0]["similarity"] == 0.77
    assert fake_retrieval.calls[0]["query"] == "retention compounds"
    assert fake_retrieval.calls[0]["top_k"] == 3


def test_search_endpoint_reports_an_unreachable_knowledge_base_safely(
    client: TestClient, fake_retrieval
) -> None:
    fake_retrieval.script(error=TranscriptSearchError("no connection to the vector store"))

    response = client.post(SEARCH_URL, json={"query": "retention"})

    assert response.status_code == 502
    assert "Traceback" not in response.text
    assert response.json()["detail"] == "Lenny's transcripts could not be searched right now. Please try again."


@pytest.mark.parametrize("payload", [{}, {"query": ""}, {"query": "hi", "top_k": 0}])
def test_search_endpoint_rejects_invalid_requests(client: TestClient, payload) -> None:
    assert client.post(SEARCH_URL, json=payload).status_code == 422


def test_respond_endpoint_reports_a_misconfigured_provider_as_503(client: TestClient, monkeypatch) -> None:
    def _fail():
        raise LLMConfigurationError(
            "LLM_MODE=ollama requires OLLAMA_MODEL.",
            user_message="The configured local model is missing. Set OLLAMA_MODEL and try again.",
        )

    monkeypatch.setattr(dev_agent, "get_application_agent", _fail)

    response = client.post(RESPOND_URL, json={"message": "Hello"})

    assert response.status_code == 503
    assert response.json()["detail"] == "The configured local model is missing. Set OLLAMA_MODEL and try again."


def test_respond_endpoint_does_not_expose_internal_details_on_failure(client: TestClient, stub_agent) -> None:
    stub_agent(error=LLMConfigurationError("ANTHROPIC_API_KEY=secret-looking-value was rejected"))

    response = client.post(RESPOND_URL, json={"message": "Hello"})

    assert response.status_code == 503
    assert "secret-looking-value" not in response.text
    assert "Traceback" not in response.text


def test_respond_endpoint_rejects_an_unknown_llm_mode(client: TestClient, stub_agent) -> None:
    stub_agent()

    response = client.post(RESPOND_URL, json={"message": "Hello", "llm_mode": "azure"})

    assert response.status_code == 503
    assert "azure" not in response.text
    assert response.json()["detail"] == (
        "The LLM configuration is incomplete. Check the LLM settings in the repository root .env file."
    )


def test_respond_endpoint_surfaces_a_failed_classification(client: TestClient, monkeypatch, scripted_client) -> None:
    agent = ApplicationAgent(client=scripted_client(text="not json at all"), llm_mode=MODE_OLLAMA)
    from app.agent.classifier import LLMIntentClassifier

    agent.router._llm_classifier = LLMIntentClassifier(agent.client)
    monkeypatch.setattr(dev_agent, "get_application_agent", lambda: agent)

    response = client.post(RESPOND_URL, json={"message": "hmm"})

    assert response.status_code == 502
    assert "not json at all" not in response.text


@pytest.mark.skipif(not get_settings().database_url, reason="DATABASE_URL is not configured")
def test_respond_endpoint_loads_only_the_requested_session_history(
    client: TestClient, monkeypatch, scripted_client, created_sessions
) -> None:
    from app.db.database import get_session_factory
    from app.services import session_service

    db = get_session_factory()()
    try:
        session = session_service.create_session(db, title="Agent API context")
        other = session_service.create_session(db, title="Other session")
        created_sessions.extend([session.id, other.id])
        session_service.add_message(db, session_id=session.id, role="user", content="first question")
        session_service.add_message(db, session_id=other.id, role="user", content="other session secret")
    finally:
        db.close()

    agent = ApplicationAgent(client=scripted_client(text="Answer."), llm_mode=MODE_OLLAMA)
    monkeypatch.setattr(dev_agent, "get_application_agent", lambda: agent)

    response = client.post(RESPOND_URL, json={"message": "follow-up", "session_id": str(session.id)})

    assert response.status_code == 200
    sent = agent.client.calls[0]["messages"]
    assert [message.content for message in sent] == ["first question", "follow-up"]
    assert "other session secret" not in str(sent)


@pytest.mark.skipif(not get_settings().database_url, reason="DATABASE_URL is not configured")
def test_respond_endpoint_reports_an_unknown_session(client: TestClient, stub_agent) -> None:
    stub_agent()

    response = client.post(RESPOND_URL, json={"message": "Hello", "session_id": str(uuid.uuid4())})

    assert response.status_code == 404


def test_dev_endpoints_are_not_registered_in_production(monkeypatch) -> None:
    production = Settings(_env_file=None, app_env="production", database_url="")
    monkeypatch.setattr(main_module, "get_settings", lambda: production)

    with TestClient(main_module.create_app()) as production_client:
        assert production_client.get(CAPABILITIES_URL).status_code == 404
        assert production_client.post(ROUTE_URL, json={"message": "Hello"}).status_code == 404
        assert production_client.post(RESPOND_URL, json={"message": "Hello"}).status_code == 404
        assert production_client.post(SEARCH_URL, json={"query": "Hello"}).status_code == 404
        assert production_client.get("/api/health").status_code == 200
        assert production_client.get("/api/sessions").status_code in {200, 503}


@pytest.mark.parametrize("app_env", ["development", "test", "local"])
def test_dev_endpoints_are_available_outside_production(monkeypatch, app_env) -> None:
    development = Settings(_env_file=None, app_env=app_env, database_url="")
    monkeypatch.setattr(main_module, "get_settings", lambda: development)

    with TestClient(main_module.create_app()) as development_client:
        assert development_client.get(CAPABILITIES_URL).status_code == 200
        assert development_client.post(ROUTE_URL, json={"message": "Hello"}).status_code == 200
