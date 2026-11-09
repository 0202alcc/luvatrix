"""llm_backend — a mini LLM backend exposed as luvatrix MCP app tools.

Run headless with MCP enabled:
    uv run python main.py run-app examples/llm_backend --render headless --mcp

App-defined tools (see docs/mcp_mode.md):
    llm_ask(question, context?) -> {"job_id": ..., "status": "pending"}
    llm_result(job_id)          -> {"status": "pending" | "done" | "error", ...}
    llm_status()                -> provider config, warnings, job counts

Jobs are processed on a background worker thread so MCP calls never block on
model latency — app tool calls execute on the runtime thread with a fixed
timeout, so long-running work must stay async (ask -> poll pattern).

LLM configuration comes from the LUVATRIX_LLM_* environment variables; see
providers.py. With nothing configured the app serves the offline echo
provider, so the full loop works with zero secrets.
"""
from __future__ import annotations

import importlib.util
import itertools
import os
import queue
import sys
import threading
import time
from pathlib import Path


def _load_providers():
    # The runtime does not extend sys.path with the app directory, so load the
    # sibling module explicitly from this file's location.
    module_path = Path(__file__).resolve().parent / "providers.py"
    spec = importlib.util.spec_from_file_location("llm_backend_app_providers", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load providers module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec: dataclasses look up sys.modules[cls.__module__]
    # while processing decorators.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


providers = _load_providers()

ASK_TOOL = {
    "name": "llm_ask",
    "description": (
        "Submit a question to the LLM backend. Returns a job_id immediately; "
        "poll llm_result with it until status is done or error."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The question to answer."},
            "context": {
                "type": "string",
                "description": "Optional context (e.g. canvas node text) to ground the answer.",
            },
        },
        "required": ["question"],
        "additionalProperties": False,
    },
}

RESULT_TOOL = {
    "name": "llm_result",
    "description": "Fetch the result of an llm_ask job. status is pending, done, or error.",
    "inputSchema": {
        "type": "object",
        "properties": {"job_id": {"type": "string", "description": "Job id from llm_ask."}},
        "required": ["job_id"],
        "additionalProperties": False,
    },
}

STATUS_TOOL = {
    "name": "llm_status",
    "description": "Report the configured LLM provider, model, warnings, and job queue counts.",
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
}


class LLMBackendApp:
    """Plain app-protocol lifecycle object with MCP tool hooks."""

    def __init__(self, provider) -> None:
        self.provider = provider
        self._jobs: dict[str, dict] = {}
        self._queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._counter = itertools.count(1)

    # ---- lifecycle ---------------------------------------------------------
    def init(self, ctx) -> None:
        del ctx
        self._stop_event.clear()
        self._worker = threading.Thread(
            target=self._run_worker, name="llm-backend-worker", daemon=True
        )
        self._worker.start()

    def loop(self, ctx, dt: float) -> None:
        del ctx, dt

    def stop(self, ctx) -> None:
        del ctx
        self._stop_event.set()
        if self._worker is not None:
            self._worker.join(timeout=5.0)
            self._worker = None

    # ---- worker ------------------------------------------------------------
    def _run_worker(self) -> None:
        while not self._stop_event.is_set():
            try:
                job_id, question, context = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                answer = self.provider.ask(question, context=context)
            except Exception as exc:  # surface provider failures on the job
                self._set_job(job_id, {"status": "error", "error": str(exc)})
            else:
                self._set_job(
                    job_id,
                    {
                        "status": "done",
                        "answer": answer.answer,
                        "model": answer.model,
                        "elapsed_ms": answer.elapsed_ms,
                    },
                )
            finally:
                self._queue.task_done()

    def _set_job(self, job_id: str, update: dict) -> None:
        with self._lock:
            self._jobs[job_id].update(update)

    # ---- MCP hooks ---------------------------------------------------------
    def mcp_tools(self) -> list[dict]:
        return [ASK_TOOL, RESULT_TOOL, STATUS_TOOL]

    def mcp_call(self, name: str, arguments: dict) -> dict:
        if name == "llm_ask":
            return self._call_ask(arguments or {})
        if name == "llm_result":
            return self._call_result(arguments or {})
        if name == "llm_status":
            return self._call_status()
        raise KeyError(name)

    def _call_ask(self, arguments: dict) -> dict:
        question = (arguments.get("question") or "").strip()
        if not question:
            raise ValueError("question must not be empty")
        context = arguments.get("context")
        if context is not None:
            context = str(context)
        job_id = f"job-{next(self._counter)}"
        with self._lock:
            self._jobs[job_id] = {"status": "pending", "created_at": time.time()}
        self._queue.put((job_id, question, context))
        return {"job_id": job_id, "status": "pending"}

    def _call_result(self, arguments: dict) -> dict:
        job_id = str(arguments.get("job_id") or "")
        with self._lock:
            job = self._jobs.get(job_id)
            result = dict(job) if job is not None else None
        if result is None:
            return {"status": "error", "error": f"unknown job_id: {job_id}"}
        result.pop("created_at", None)
        return result

    def _call_status(self) -> dict:
        with self._lock:
            counts = {"pending": 0, "done": 0, "error": 0}
            for job in self._jobs.values():
                status = job.get("status")
                if status in counts:
                    counts[status] += 1
        # Secrets never leave this method: provider name/model/warnings only.
        return {
            "provider": self.provider.name,
            "model": self.provider.model,
            "warnings": list(getattr(self.provider, "warnings", ())),
            "queue_depth": self._queue.qsize(),
            "jobs": counts,
        }

    def mcp_state(self) -> dict:
        with self._lock:
            total = len(self._jobs)
        return {
            "provider": self.provider.name,
            "model": self.provider.model,
            "jobs_total": total,
        }


def create() -> LLMBackendApp:
    return LLMBackendApp(providers.resolve_provider(os.environ))
