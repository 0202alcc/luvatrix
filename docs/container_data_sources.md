# Container Data Sources Protocol (Draft v0)

Status: Draft, non-normative. Defines the intended contract for dynamic
backends behind the container format — designed so the backend can be
written in **any language**, because the contract is HTTP + JSON, not an
implementation.

## 1. Design Position

The web tiers ship no backend by design: the static tier is a pure static
site and the Pyodide tier runs Python in the browser. When an app needs
dynamic services (data, auth, persistence), the container *declares* what
it needs and the frontend runtime fetches over HTTP. The server stays a
dumb static host; the backend is whatever serves the declared endpoints —
Django, Go, Node, Rails, Cloudflare Workers, anything that speaks HTTP.

This mirrors how rendering achieved language neutrality: the command
buffer standardized the renderer contract, and this protocol standardizes
the data contract.

## 2. Container Declaration

A `data_sources` section (top-level, aligning with the optional section
already sketched in `docs/planes_protocol_v0.md`):

```json
"data_sources": [
  {
    "id": "projects",
    "url": "https://api.example.com/projects",
    "poll_ms": 30000,
    "headers": {"X-Client": "luvatrix-app"},
    "initial": {"items": []}
  }
]
```

Fields (v0):

1. `id: str` — unique key; fetched payloads land in app state under
   `data_sources.<id>`.
2. `url: str` — absolute or build-relative; responses must be JSON.
3. `poll_ms: int | null` — optional polling cadence; `null` (default)
   fetches once on mount.
4. `headers: object | null` — static request headers. The container is
   public data: **no secrets here** (see §6).
5. `initial: object | null` — placeholder rendered before the first
   fetch resolves.

## 3. Runtime Contract

1. Fetches are `GET`, `Accept: application/json`; non-2xx responses set
   the source to an error marker (`{"__error__": status}`) rather than
   crashing the render loop.
2. The static runtime fetches with the browser `fetch` API; the Pyodide
   tier fetches through `pyodide.http` into the same app-state slot, so
   both tiers observe identical shapes.
3. Invalidation: `poll_ms` polling; JS handlers may request a refresh via
   `event.refreshDataSource(id)` (mirrors `fireTrigger` in the handler
   contract). Python handlers refresh through the same state slot.
4. Fetched data does **not** participate in determinism/parity checks —
   it is ambient input, like HDI events. Rendering stays deterministic
   given state; sources only mutate state.

## 4. Component Binding (Intended)

Components gain an optional `data_binding` for text props:

```json
"props": {"data_text": {"source": "projects", "path": "items.0.name", "fallback": "Loading..."}}
```

The runtime resolves `path` against the fetched payload each frame;
`fallback` renders until data lands. This keeps data-driven text
declarative (no handler required), with JS/Python handlers available for
anything imperative.

## 5. Reference Flow

```text
container.json --(data_sources)--> runtime fetch --HTTP+JSON--> any-language backend
        |                                   |
        +-- components (data_binding) <-----+  state["data_sources"][id]
```

## 6. Security Notes

1. No credentials in the container — it ships to every client. Auth flows
   belong to the backend (cookies, tokens acquired at runtime by
   handlers).
2. Backends must send permissive CORS for browser tiers, or same-origin
   proxying must be configured at the static host.
3. Runtime treats all fetched data as untrusted input: paths resolve
   defensively, and oversized payloads are truncated by the fetch layer.

## 7. Implementation Status

Not yet implemented — this document fixes the contract before the first
implementation (static-tier fetch + `data_binding` text rendering are the
intended v1). Changes before implementation land as edits here, not
silent runtime drift.
