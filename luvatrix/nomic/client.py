"""Typed client for the Nomic Platform's public v0 API.

Request/response shapes derive from drive-next `packages/api/src/v0`
(agents, files, projects). Everything sits on `luvatrix.net.HttpClient`,
so bearer auth can come straight from `WorkosConnectClient.access_token`.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping, Sequence
from urllib.parse import urlencode

from ..net import BearerToken, HttpClient, Transport

AGENT_STATUSES = ("waiting", "running", "awaiting_tool", "finished", "stopped", "failed")


@dataclass(frozen=True)
class AgentArtifact:
    id: str
    type: str
    name: str
    created_at: str


@dataclass(frozen=True)
class AgentSummary:
    id: str
    status: str
    title: str | None
    workflow_id: str | None
    workflow_name: str | None
    workflow_version_id: str | None
    project_id: str | None
    project_name: str | None
    artifacts: tuple[AgentArtifact, ...]
    created_at: str
    updated_at: str
    retry: Mapping[str, object] | None = None


@dataclass(frozen=True)
class AgentDetail(AgentSummary):
    active_file_ids: tuple[str, ...] = ()
    parent_session_id: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class AgentListPage:
    agents: tuple[AgentSummary, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class ConversationMessage:
    """One message from `GET /agents/{id}/conversation`.

    `type` discriminates the payload: user, assistant, narration, error,
    thinking, tool, or compaction. Fields that do not apply to a type are
    None.
    """

    id: str
    created_at: str
    type: str
    text: str | None = None
    tool_name: str | None = None
    status: str | None = None
    error: str | None = None
    redacted: bool | None = None


@dataclass(frozen=True)
class Conversation:
    id: str
    messages: tuple[ConversationMessage, ...]


@dataclass(frozen=True)
class UploadedFile:
    id: str
    name: str
    mime_type: str
    size: int
    file_type: str
    parent_id: str | None
    file_version_id: str
    created_at: str
    status: str


@dataclass(frozen=True)
class FileSearchResult:
    id: str
    name: str
    mime_type: str
    parent_id: str | None
    path: str


@dataclass(frozen=True)
class FileSearchPage:
    files: tuple[FileSearchResult, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class NomicProject:
    id: str
    name: str
    description: str | None
    project_number: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ProjectListPage:
    projects: tuple[NomicProject, ...]
    next_cursor: str | None
    total_count: int | None


@dataclass(frozen=True)
class NomicClient:
    """Minimal typed client for one Nomic workspace's `/api/v0`."""

    workspace_url: str
    transport: Transport | None = None
    bearer_token: BearerToken | None = None
    timeout: float | None = None

    def __post_init__(self) -> None:
        if not self.workspace_url.strip():
            raise ValueError("workspace_url is required")
        base = f"{self.workspace_url.rstrip('/')}/api/v0"
        object.__setattr__(
            self,
            "_http",
            HttpClient(
                base,
                transport=self.transport,
                bearer_token=self.bearer_token,
                timeout=self.timeout,
            ),
        )

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    def launch_agent(
        self,
        prompt: str | None = None,
        *,
        file_ids: Sequence[str] | None = None,
        project_id: str | None = None,
        workflow_id: str | None = None,
        workflow_version_id: str | None = None,
        workflow_inputs: Mapping[str, str | Sequence[str] | None] | None = None,
        capabilities: Mapping[str, object] | None = None,
        model: str | None = None,
        mode: str | None = None,
    ) -> AgentDetail:
        """Launch a background agent. Returns the created agent (HTTP 201).

        A simple agent runs from `prompt` with optional `file_ids`; pass
        `workflow_id` to run a workflow, whose file slots go in
        `workflow_inputs` instead of `prompt`.
        """
        body: dict[str, object] = {}
        if prompt is not None:
            body["prompt"] = {"text": prompt}
        if file_ids is not None:
            body["fileIds"] = list(file_ids)
        if project_id is not None:
            body["projectId"] = project_id
        if workflow_id is not None:
            body["workflowId"] = workflow_id
        if workflow_version_id is not None:
            body["workflowVersionId"] = workflow_version_id
        if workflow_inputs is not None:
            body["workflowInputs"] = {
                name: ([*value] if isinstance(value, (list, tuple)) else value)
                for name, value in workflow_inputs.items()
            }
        if capabilities is not None:
            body["capabilities"] = dict(capabilities)
        if model is not None:
            body["model"] = model
        if mode is not None:
            body["mode"] = mode
        payload = self._http.post_json("/agents", body)
        return _agent_detail(_data(payload))

    def list_agents(
        self,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        status: str | None = None,
        workflow_id: str | None = None,
    ) -> AgentListPage:
        """List the caller's agents, newest first.

        `status` is one of AGENT_STATUSES; `workflow_id` filters by workflow,
        with the literal "null" excluding workflow agents.
        """
        payload = self._http.get_json(
            _with_query(
                "/agents",
                {
                    "limit": limit,
                    "cursor": cursor,
                    "status": status,
                    "workflowId": workflow_id,
                },
            )
        )
        data = _data(payload)
        if not isinstance(data, list):
            raise _contract_error("agents list", payload)
        return AgentListPage(
            agents=tuple(_agent_summary(item) for item in data),
            next_cursor=_optional_str(payload.get("nextCursor")),
        )

    def get_agent(self, agent_id: str) -> AgentDetail:
        return _agent_detail(_data(self._http.get_json(f"/agents/{agent_id}")))

    def stop_agent(self, agent_id: str) -> AgentSummary:
        """Request cancellation; poll `get_agent` for the terminal status."""
        response = self._http.request("POST", f"/agents/{agent_id}/stop")
        return _agent_summary(_data(json.loads(response.body) if response.body else None))

    def followup_agent(self, agent_id: str, prompt: str) -> AgentDetail:
        """Queue a new turn on a finished/stopped/failed agent (HTTP 202)."""
        payload = self._http.post_json(
            f"/agents/{agent_id}/followup",
            {"prompt": {"text": prompt}},
        )
        return _agent_detail(_data(payload))

    def get_conversation(
        self,
        agent_id: str,
        *,
        include: Sequence[str] = (),
    ) -> Conversation:
        """The agent's ordered messages; `include=("steps",)` adds tool/thinking rows."""
        payload = self._http.get_json(
            _with_query(
                f"/agents/{agent_id}/conversation",
                {"include": ",".join(include) if include else None},
            )
        )
        data = _data(payload)
        messages = data.get("messages") if isinstance(data, dict) else None
        if not isinstance(messages, list):
            raise _contract_error("conversation", payload)
        return Conversation(
            id=str(data.get("id") or agent_id),
            messages=tuple(_conversation_message(item) for item in messages),
        )

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    def upload_file(
        self,
        content: bytes,
        *,
        filename: str,
        content_type: str = "application/octet-stream",
        path: str | None = None,
        parent_id: str | None = None,
    ) -> UploadedFile:
        """Upload via `multipart/form-data`. `path` is slash-delimited and may
        name intermediate folders; `parent_id` uploads into an existing folder.
        The response is not wrapped in `data`."""
        fields: dict[str, str] = {}
        if path is not None:
            fields["path"] = path
        if parent_id is not None:
            fields["parentId"] = parent_id
        payload = self._http.post_multipart(
            "/files/upload",
            fields=fields,
            file_field="file",
            filename=filename,
            content=content,
            content_type=content_type,
        )
        if not isinstance(payload, dict):
            raise _contract_error("uploaded file", payload)
        return UploadedFile(
            id=str(payload.get("id") or ""),
            name=str(payload.get("name") or ""),
            mime_type=str(payload.get("mimeType") or ""),
            size=int(payload.get("size") or 0),
            file_type=str(payload.get("fileType") or ""),
            parent_id=_optional_str(payload.get("parentId")),
            file_version_id=str(payload.get("fileVersionId") or ""),
            created_at=str(payload.get("createdAt") or ""),
            status=str(payload.get("status") or ""),
        )

    def search_files(
        self,
        query: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        integration_id: str | None = None,
    ) -> FileSearchPage:
        payload = self._http.get_json(
            _with_query(
                "/files/search",
                {
                    "query": query,
                    "limit": limit,
                    "cursor": cursor,
                    "integrationId": integration_id,
                },
            )
        )
        data = _data(payload)
        if not isinstance(data, list):
            raise _contract_error("file search", payload)
        return FileSearchPage(
            files=tuple(
                FileSearchResult(
                    id=str(item.get("id") or ""),
                    name=str(item.get("name") or ""),
                    mime_type=str(item.get("mimeType") or ""),
                    parent_id=_optional_str(item.get("parentId")),
                    path=str(item.get("path") or ""),
                )
                for item in data
            ),
            next_cursor=_optional_str(payload.get("nextCursor")),
        )

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def list_projects(
        self,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        search: str | None = None,
        membership: str | None = None,
    ) -> ProjectListPage:
        """List visible projects; `membership="mine"` narrows to joined ones."""
        payload = self._http.get_json(
            _with_query(
                "/projects",
                {
                    "limit": limit,
                    "cursor": cursor,
                    "search": search,
                    "membership": membership,
                },
            )
        )
        data = _data(payload)
        if not isinstance(data, list):
            raise _contract_error("projects list", payload)
        total = payload.get("totalCount")
        return ProjectListPage(
            projects=tuple(
                NomicProject(
                    id=str(item.get("id") or ""),
                    name=str(item.get("name") or ""),
                    description=_optional_str(item.get("description")),
                    project_number=_optional_str(item.get("projectNumber")),
                    created_at=str(item.get("createdAt") or ""),
                    updated_at=str(item.get("updatedAt") or ""),
                )
                for item in data
            ),
            next_cursor=_optional_str(payload.get("nextCursor")),
            total_count=int(total) if isinstance(total, (int, float)) else None,
        )


def _with_query(path: str, params: Mapping[str, object | None]) -> str:
    query = {key: str(value) for key, value in params.items() if value is not None}
    return f"{path}?{urlencode(query)}" if query else path


def _data(payload: object) -> object:
    if not isinstance(payload, dict) or "data" not in payload:
        raise _contract_error("data-wrapped", payload)
    return payload["data"]


def _optional_str(value: object) -> str | None:
    return str(value) if isinstance(value, str) and value else None


def _contract_error(kind: str, payload: object) -> ValueError:
    return ValueError(f"Nomic API returned an unexpected {kind} payload: {payload!r:.200}")


def _agent_summary(payload: object) -> AgentSummary:
    if not isinstance(payload, dict):
        raise _contract_error("agent", payload)
    artifacts = payload.get("artifacts") or []
    retry = payload.get("retry")
    return AgentSummary(
        id=str(payload.get("id") or ""),
        status=str(payload.get("status") or ""),
        title=_optional_str(payload.get("title")),
        workflow_id=_optional_str(payload.get("workflowId")),
        workflow_name=_optional_str(payload.get("workflowName")),
        workflow_version_id=_optional_str(payload.get("workflowVersionId")),
        project_id=_optional_str(payload.get("projectId")),
        project_name=_optional_str(payload.get("projectName")),
        artifacts=tuple(
            AgentArtifact(
                id=str(item.get("id") or ""),
                type=str(item.get("type") or ""),
                name=str(item.get("name") or ""),
                created_at=str(item.get("createdAt") or ""),
            )
            for item in artifacts
        ),
        created_at=str(payload.get("createdAt") or ""),
        updated_at=str(payload.get("updatedAt") or ""),
        retry=retry if isinstance(retry, dict) else None,
    )


def _agent_detail(payload: object) -> AgentDetail:
    summary = _agent_summary(payload)
    raw = payload if isinstance(payload, dict) else {}
    active_ids = raw.get("activeFileIds") or []
    return AgentDetail(
        **{f.name: getattr(summary, f.name) for f in summary.__dataclass_fields__.values()},
        active_file_ids=tuple(str(item) for item in active_ids),
        parent_session_id=_optional_str(raw.get("parentSessionId")),
        model=_optional_str(raw.get("model")),
    )


def _conversation_message(payload: object) -> ConversationMessage:
    if not isinstance(payload, dict):
        raise _contract_error("conversation message", payload)
    redacted = payload.get("redacted")
    return ConversationMessage(
        id=str(payload.get("id") or ""),
        created_at=str(payload.get("createdAt") or ""),
        type=str(payload.get("type") or ""),
        text=_optional_str(payload.get("text")),
        tool_name=_optional_str(payload.get("toolName")),
        status=_optional_str(payload.get("status")),
        error=_optional_str(payload.get("error")),
        redacted=redacted if isinstance(redacted, bool) else None,
    )
