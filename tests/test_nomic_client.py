from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest

from luvatrix.net import ApiError, HttpRequest, HttpResponse
from luvatrix.nomic import (
    AgentDetail,
    AgentSummary,
    NomicClient,
)

WORKSPACE = "https://tenant.example.com"
AGENT_ID = "019a0f4e-7c2b-7f31-9f8d-2a3b4c5d6e7f"

AGENT_SUMMARY_PAYLOAD = {
    "id": AGENT_ID,
    "status": "running",
    "title": "Summarize Q3 report",
    "retry": None,
    "workflowId": None,
    "workflowName": None,
    "workflowVersionId": None,
    "projectId": "019a0f4e-0000-7000-8000-0000000000aa",
    "projectName": "HQ Renovation",
    "artifacts": [
        {
            "id": "019a0f4e-0000-7000-8000-0000000000bb",
            "type": "table",
            "name": "Budget lines",
            "createdAt": "2026-11-01T10:00:00.000Z",
        }
    ],
    "createdAt": "2026-11-01T09:00:00.000Z",
    "updatedAt": "2026-11-01T09:30:00.000Z",
}

AGENT_DETAIL_PAYLOAD = {
    **AGENT_SUMMARY_PAYLOAD,
    "activeFileIds": ["019a0f4e-0000-7000-8000-0000000000cc"],
    "parentSessionId": None,
    "model": "claude-sonnet-5-5",
}

PROJECT_PAYLOAD = {
    "id": "019a0f4e-0000-7000-8000-0000000000aa",
    "name": "HQ Renovation",
    "description": "Phase 2",
    "projectNumber": "PRJ-104",
    "createdAt": "2026-10-01T08:00:00.000Z",
    "updatedAt": "2026-10-02T08:00:00.000Z",
}

UPLOAD_PAYLOAD = {
    "id": "019a0f4e-0000-7000-8000-0000000000dd",
    "name": "quarterly.pdf",
    "mimeType": "application/pdf",
    "size": 9,
    "fileType": "DOCUMENT",
    "parentId": None,
    "fileVersionId": "019a0f4e-0000-7000-8000-0000000000ee",
    "createdAt": "2026-11-04T09:00:00.000Z",
    "status": "processing",
}

CONVERSATION_PAYLOAD = {
    "data": {
        "id": AGENT_ID,
        "messages": [
            {"id": "m1", "createdAt": "2026-11-01T09:00:00.000Z", "type": "user", "text": "Summarize this"},
            {"id": "m2", "createdAt": "2026-11-01T09:00:01.000Z", "type": "assistant", "text": "Sure"},
            {
                "id": "m3",
                "createdAt": "2026-11-01T09:00:02.000Z",
                "type": "tool",
                "toolName": "read_file",
                "status": "completed",
            },
            {"id": "m4", "createdAt": "2026-11-01T09:00:03.000Z", "type": "thinking", "redacted": True},
        ],
    }
}


class FakeTransport:
    def __init__(self) -> None:
        self.requests: list[HttpRequest] = []
        self._queue: list[HttpResponse] = []

    def queue(self, status: int, payload: object) -> None:
        self._queue.append(
            HttpResponse(status=status, headers={}, body=json.dumps(payload).encode("utf-8"))
        )

    def send(self, request: HttpRequest, *, timeout: float | None = None) -> HttpResponse:
        self.requests.append(request)
        assert self._queue, "FakeTransport received an unqueued request"
        return self._queue.pop(0)


def _client(transport: FakeTransport, **kwargs: object) -> NomicClient:
    return NomicClient(WORKSPACE, transport=transport, bearer_token="tok", **kwargs)  # type: ignore[arg-type]


def _query_of(request: HttpRequest) -> dict[str, list[str]]:
    return parse_qs(urlparse(request.url).query)


def test_launch_agent_posts_prompt_and_parses_detail() -> None:
    transport = FakeTransport()
    transport.queue(201, {"data": AGENT_DETAIL_PAYLOAD})
    client = _client(transport)

    agent = client.launch_agent("Summarize the Q3 report", project_id=PROJECT_PAYLOAD["id"])

    request = transport.requests[0]
    assert request.method == "POST"
    assert request.url == f"{WORKSPACE}/api/v0/agents"
    assert request.headers["Authorization"] == "Bearer tok"
    assert json.loads(request.body or b"") == {
        "prompt": {"text": "Summarize the Q3 report"},
        "projectId": PROJECT_PAYLOAD["id"],
    }

    assert isinstance(agent, AgentDetail)
    assert agent.id == AGENT_ID
    assert agent.status == "running"
    assert agent.title == "Summarize Q3 report"
    assert agent.project_name == "HQ Renovation"
    assert agent.model == "claude-sonnet-5-5"
    assert agent.active_file_ids == ("019a0f4e-0000-7000-8000-0000000000cc",)
    assert agent.parent_session_id is None
    assert agent.artifacts[0].name == "Budget lines"
    assert agent.artifacts[0].type == "table"


def test_launch_agent_supports_workflow_inputs_and_file_ids() -> None:
    transport = FakeTransport()
    transport.queue(201, {"data": AGENT_DETAIL_PAYLOAD})
    client = _client(transport)

    client.launch_agent(
        workflow_id="019a0f4e-0000-7000-8000-0000000000ff",
        workflow_inputs={"drawings": ["f-1", "f-2"], "spec": None},
        mode="medium",
        model="claude-sonnet-5-5",
    )

    body = json.loads(transport.requests[0].body or b"")
    assert body == {
        "workflowId": "019a0f4e-0000-7000-8000-0000000000ff",
        "workflowInputs": {"drawings": ["f-1", "f-2"], "spec": None},
        "mode": "medium",
        "model": "claude-sonnet-5-5",
    }

    transport.queue(201, {"data": AGENT_DETAIL_PAYLOAD})
    client.launch_agent("Read these", file_ids=["f-9"])
    body = json.loads(transport.requests[1].body or b"")
    assert body == {"prompt": {"text": "Read these"}, "fileIds": ["f-9"]}


def test_list_agents_sends_filters_and_parses_page() -> None:
    transport = FakeTransport()
    transport.queue(200, {"data": [AGENT_SUMMARY_PAYLOAD], "nextCursor": "cursor-2"})
    client = _client(transport)

    page = client.list_agents(limit=10, cursor="cursor-1", status="running", workflow_id="null")

    request = transport.requests[0]
    assert request.method == "GET"
    query = _query_of(request)
    assert query == {
        "limit": ["10"],
        "cursor": ["cursor-1"],
        "status": ["running"],
        "workflowId": ["null"],
    }
    assert page.next_cursor == "cursor-2"
    assert len(page.agents) == 1
    agent = page.agents[0]
    assert isinstance(agent, AgentSummary)
    assert agent.id == AGENT_ID
    assert agent.status == "running"
    assert agent.created_at == "2026-11-01T09:00:00.000Z"


def test_list_agents_omits_unset_filters() -> None:
    transport = FakeTransport()
    transport.queue(200, {"data": [], "nextCursor": None})
    client = _client(transport)

    page = client.list_agents()

    assert _query_of(transport.requests[0]) == {}
    assert page.agents == ()
    assert page.next_cursor is None


def test_get_agent_returns_detail() -> None:
    transport = FakeTransport()
    transport.queue(200, {"data": AGENT_DETAIL_PAYLOAD})
    client = _client(transport)

    agent = client.get_agent(AGENT_ID)

    assert transport.requests[0].url == f"{WORKSPACE}/api/v0/agents/{AGENT_ID}"
    assert agent.model == "claude-sonnet-5-5"


def test_get_agent_propagates_api_error() -> None:
    transport = FakeTransport()
    transport.queue(404, {"error": "Agent not found", "code": "not_found"})
    client = _client(transport)

    with pytest.raises(ApiError) as caught:
        client.get_agent("nope")
    assert caught.value.status == 404


def test_stop_agent_posts_and_returns_summary() -> None:
    transport = FakeTransport()
    transport.queue(200, {"data": {**AGENT_SUMMARY_PAYLOAD, "status": "stopped"}})
    client = _client(transport)

    agent = client.stop_agent(AGENT_ID)

    request = transport.requests[0]
    assert request.method == "POST"
    assert request.url == f"{WORKSPACE}/api/v0/agents/{AGENT_ID}/stop"
    assert request.body is None
    assert isinstance(agent, AgentSummary)
    assert agent.status == "stopped"


def test_followup_agent_posts_prompt_and_accepts_202() -> None:
    transport = FakeTransport()
    transport.queue(202, {"data": {**AGENT_DETAIL_PAYLOAD, "status": "waiting"}})
    client = _client(transport)

    agent = client.followup_agent(AGENT_ID, "Now with the electrical drawings")

    request = transport.requests[0]
    assert request.method == "POST"
    assert request.url == f"{WORKSPACE}/api/v0/agents/{AGENT_ID}/followup"
    assert json.loads(request.body or b"") == {"prompt": {"text": "Now with the electrical drawings"}}
    assert agent.status == "waiting"


def test_get_conversation_parses_typed_messages() -> None:
    transport = FakeTransport()
    transport.queue(200, CONVERSATION_PAYLOAD)
    client = _client(transport)

    conversation = client.get_conversation(AGENT_ID, include=("steps",))

    query = _query_of(transport.requests[0])
    assert query == {"include": ["steps"]}
    assert conversation.id == AGENT_ID
    assert [(m.type, m.text) for m in conversation.messages[:2]] == [
        ("user", "Summarize this"),
        ("assistant", "Sure"),
    ]
    tool = conversation.messages[2]
    assert tool.tool_name == "read_file"
    assert tool.status == "completed"
    thinking = conversation.messages[3]
    assert thinking.redacted is True
    assert thinking.text is None


def test_upload_file_posts_multipart_and_parses_response() -> None:
    transport = FakeTransport()
    transport.queue(200, UPLOAD_PAYLOAD)
    client = _client(transport)

    uploaded = client.upload_file(
        b"%PDF-fake",
        filename="quarterly.pdf",
        content_type="application/pdf",
        path="reports/2026/quarterly.pdf",
    )

    request = transport.requests[0]
    assert request.method == "POST"
    assert request.url == f"{WORKSPACE}/api/v0/files/upload"
    assert request.headers["Content-Type"].startswith("multipart/form-data; boundary=")
    body = request.body or b""
    assert b'name="path"' in body and b"reports/2026/quarterly.pdf" in body
    assert b'name="file"; filename="quarterly.pdf"' in body
    assert b"%PDF-fake" in body

    assert uploaded.id == UPLOAD_PAYLOAD["id"]
    assert uploaded.name == "quarterly.pdf"
    assert uploaded.mime_type == "application/pdf"
    assert uploaded.size == 9
    assert uploaded.parent_id is None
    assert uploaded.file_version_id == UPLOAD_PAYLOAD["fileVersionId"]
    assert uploaded.status == "processing"


def test_search_files_parses_results_and_cursor() -> None:
    transport = FakeTransport()
    result = {
        "id": UPLOAD_PAYLOAD["id"],
        "name": "quarterly.pdf",
        "mimeType": "application/pdf",
        "parentId": None,
        "path": "Uploads/quarterly.pdf",
    }
    transport.queue(200, {"data": [result], "nextCursor": None})
    client = _client(transport)

    page = client.search_files("quarterly", limit=25)

    query = _query_of(transport.requests[0])
    assert query == {"query": ["quarterly"], "limit": ["25"]}
    assert len(page.files) == 1
    assert page.files[0].path == "Uploads/quarterly.pdf"
    assert page.files[0].parent_id is None
    assert page.next_cursor is None


def test_list_projects_parses_page_and_total() -> None:
    transport = FakeTransport()
    transport.queue(200, {"data": [PROJECT_PAYLOAD], "nextCursor": "c-9", "totalCount": 42})
    client = _client(transport)

    page = client.list_projects(search="HQ", membership="mine")

    query = _query_of(transport.requests[0])
    assert query == {"search": ["HQ"], "membership": ["mine"]}
    assert page.total_count == 42
    assert page.next_cursor == "c-9"
    project = page.projects[0]
    assert project.id == PROJECT_PAYLOAD["id"]
    assert project.name == "HQ Renovation"
    assert project.project_number == "PRJ-104"
    assert project.description == "Phase 2"


def test_workspace_url_trailing_slash_is_tolerated() -> None:
    transport = FakeTransport()
    transport.queue(200, {"data": AGENT_DETAIL_PAYLOAD})
    client = NomicClient(f"{WORKSPACE}/", transport=transport, bearer_token="t")

    client.get_agent(AGENT_ID)

    assert transport.requests[0].url == f"{WORKSPACE}/api/v0/agents/{AGENT_ID}"
