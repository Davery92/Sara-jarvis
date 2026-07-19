# Artifacts Studio + Surfaces — Sara-Built Content & UI

**Status:** Parts A AND B SHIPPED 2026-07-08 on assistant-experience-jarvis.
Part A (Artifacts Studio + doc gen) A-1..A-4; Part B (interactive surfaces +
workspace jobs) S1..S5 — all implemented & verified end-to-end (web + backend +
Celery). iOS renderers (A-4 files, S5 surfaces) are code-complete but need an
app rebuild for the new expo-file-system/expo-sharing native modules.
**Branch context:** assistant-experience-jarvis
**Companion docs:** ASSISTANT_EXPERIENCE_PLAN.md, CODE_MODE_DESIGN.md

## 0. Scope, reprioritized (2026-07-08)

David's core ask, in priority order:

1. **Artifacts Studio (Part A — build first).** The artifact feature promoted
   out of the chat side-panel into its own dedicated area: a persistent
   library of everything Sara has built, browsable, searchable, full-screen.
   "The artifact feature built into its own area — that's the biggest benefit."
2. **Document generation (Part A).** A tool for Sara to produce real files —
   **Word docs and PDFs** — on explicit request, landing in the Studio with a
   download button.
3. **Interactive surfaces (Part B — later).** The live checklist / recipe
   cook-mode / file-pickup system from the original design. Kept, deprioritized.

The cardinal rule is unchanged and applies to everything here: **explicit
invocation only.** Sara never builds an artifact, document, or surface
because she thinks it would be nice. See §A5.

---

# Part A — Artifacts Studio + Document Generation

## A1. What already exists (most of the backbone)

| Piece | Where | State |
|---|---|---|
| `Artifact` model (`artifacts` table: artifact_type, title, content JSONB, artifact_metadata, is_pinned, conversation_id/episode_id) | `backend/app/models/artifact.py` | Done |
| Full CRUD API | `backend/app/routes/artifacts.py`, mounted at `/api/artifacts` (main_simple.py:5744) | Done |
| Renderers: Code, Diagram, Document, Mindmap, Note | `frontend/src/components/canvas/artifacts/*.tsx` + `ArtifactRenderer.tsx` | Done |
| Canvas tools emitting `canvas_command` SSE mid-stream | `backend/app/tools/canvas.py`, forwarded in main_simple.py ~1885 | Done |
| Word generation lib | `python-docx==1.1.0` already in requirements.txt | Done |
| PDF **extraction** | `pypdf==3.17.1` — extraction only, cannot generate | n/a |

What's missing is exactly the two things David asked for:
- A **library view**: canvas artifacts appear in a transient side panel and
  (at best) sit unseen in the `artifacts` table. There is no AppView to
  browse, reopen, pin, search, or delete them.
- **File output**: nothing can produce a `.docx` or `.pdf`.

## A2. Artifacts Studio (dedicated area)

New view `artifacts` in `frontend/src/navigation/views.ts` (`AppView` union +
`APP_VIEWS` entry — label "Studio", path `/artifacts`; keywords: artifact,
studio, docs, files).

**Layout** (matches existing dark theme):
- **Library pane**: grid of artifact cards (type icon, title, updated_at,
  pinned badge), pinned-first, filter chips by `artifact_type`, text search
  (title match server-side via existing list endpoint + a `q` param).
- **Viewer pane**: full-width render of the selected artifact, reusing
  `ArtifactRenderer` and the five existing renderers **moved/shared out of the
  canvas directory** (import them; don't fork). Editable where the renderer
  already supports it (document/note/code). New `FileArtifact.tsx` renderer
  for generated files (§A3): file card + preview (PDF inline via browser
  viewer; docx shows metadata + source markdown) + Download button.
- Actions: pin/unpin, rename, delete, "ask Sara to revise" (deep-link into
  chat with the artifact referenced).

**Persistence wiring change**: `canvas_open` today only emits the SSE command —
nothing guarantees a row exists. Change: `CanvasOpenTool.execute()` (and the
new generation tools) **write the Artifact row first**, then emit the command
including `artifact_id`. Everything Sara builds is in the library by
construction; the canvas panel becomes just another window onto the same rows.
`canvas_update` patches the row by id. (Frontend-initiated edits already go
through `/api/artifacts` CRUD.)

**Chat → Studio handoff**: the SSE consumer keeps opening the side panel as
today (nice for in-conversation glanceability), but the panel header gains
"Open in Studio". For voice-originated builds with no SSE stream, reuse the
Redis mirror pattern (`workspace_commands:{user_id}`, 60s TTL) and/or
`command_router.open_url` to the `/artifacts?id=…` deep link on the best
device.

## A3. Document generation (Word + PDF)

New tool `document_generate` (registry category `authoring`):

```jsonc
{
  "name": "document_generate",
  "parameters": {
    "format":  { "enum": ["docx", "pdf"] },
    "title":   { "type": "string" },
    "content": { "type": "string", "description": "Full document body in markdown" },
    "style":   { "enum": ["default", "letter", "report"], "default": "default" }
  }
}
```

**Pipeline** (new `backend/app/services/document_renderer.py`):
- Input is always **markdown** — Sara is reliable at markdown, and one input
  format keeps the tool schema trivial.
- **docx**: markdown → `python-docx` via a compact converter (headings,
  paragraphs, bold/italic/code, bullet + numbered lists, tables, page title).
  Lib is already installed; no Dockerfile change.
- **pdf**: markdown → HTML (`python-markdown`) → **WeasyPrint** with a house
  print stylesheet per `style` (clean serif letter, report with title page +
  page numbers). Requires adding `weasyprint` to requirements **and** its
  system deps (`libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0`) to
  the backend Dockerfile → **container rebuild required** (deployed-code-lags
  gotcha). Chosen over reportlab because HTML+CSS gives far better typography
  per unit of effort and we already trade in markdown/HTML.
- Output → MinIO (`sara-docs` bucket, key `artifacts/{user_id}/{artifact_id}/{filename}`
  via `docs_ingest.store_file`) → `Artifact` row with `artifact_type="file"`,
  `content = {storage_key, filename, mime, size_bytes, format, source_markdown}`.
  Keeping `source_markdown` means "revise the intro and re-export" is a
  regenerate, not an edit-the-binary problem.
- Tool result emits `canvas_command: open` with the file artifact → chat shows
  the file card immediately; it's in the Studio permanently.

**Download endpoint**: `GET /api/artifacts/{id}/download` — auth via standard
cookie (`get_current_user`), ownership check, stream bytes from MinIO
(`get_file`), `Content-Disposition: attachment`. No presigned URLs (none exist
in the codebase; streaming keeps auth in one place). Works from any logged-in
device, which covers "download to my current device."

**Revision flow**: "Sara, tighten section 2 of that proposal" → she reads
`source_markdown` (via a `artifact_read` tool or the existing GET), edits,
calls `document_generate` again with the same artifact referenced →
regenerates file, updates the same row (version bump in `artifact_metadata`).

## A4. Tools summary (Part A)

| Tool | Purpose | Notes |
|---|---|---|
| `document_generate` | Markdown → docx/pdf file artifact | New |
| `artifact_read` | Fetch an artifact's content/source for revision | New, thin wrapper over CRUD |
| `canvas_open` / `canvas_update` | Unchanged UX, now persist Artifact rows | Modified |

## A5. Invocation gating (Part A)

Document/artifact generation is naturally explicit ("write that up as a PDF",
"make me a Word doc for…"), so Part A needs lighter gating than surfaces:

1. **Origin lock**: `document_generate` sets `requires_user_origin = True` —
   uncallable from deliberation/reactive/Celery paths. Hard, in code.
2. **Prompt contract**: description opens with *"ONLY when David explicitly
   asks for a document/file. If you think one would help, offer in chat and
   wait."*
3. Proactive systems may **suggest** ("want this as a PDF?") through their
   normal channels; David's yes in chat is the explicit trigger.

No progressive-disclosure schema gating needed for Part A — misfiring costs a
stray library entry, not an email crawl. (Part B keeps the stricter regime.)

## A6. Part A build order

| Phase | Scope | Proves |
|---|---|---|
| **A-1** | `artifacts` AppView + Studio library/viewer reusing existing renderers; canvas tools persist rows; "Open in Studio" | Artifacts have a home; nothing Sara builds evaporates |
| **A-2** | `document_renderer.py` docx path (lib already present), `document_generate` tool (docx only), `artifact_type="file"` + `FileArtifact` renderer + download endpoint | "Make me a Word doc of this" end-to-end, no Docker changes |
| **A-3** | WeasyPrint + Dockerfile deps, pdf path, `style` presets, revision flow (`artifact_read`, version bump) | "Make it a PDF" + iterate-on-document |
| **A-4** | iOS: Studio list + file download/share sheet, `content_card` for generated files | Mobile access |

---

# Part B — Interactive Surfaces (deferred)

Everything below is the original surfaces design, unchanged in substance,
scheduled after Part A ships. Summary retained for continuity; the full
earlier text follows.

## B1. Concept

Server-driven **interactive** UI: Sara composes a JSON spec from a closed
component vocabulary (`markdown`, `checklist`, `steps`, `timer`, `file_list`,
`table`, `form`, `buttons`, `progress`); a **Custom** view renders it;
interactions flow back as events (per-component `notify` flag — default
silent state writes, opt-in "wake Sara" for things like "I'm done shopping");
she updates or tears the surface down on request. Backed by a new `surface`
table (spec JSONB + mutable state JSONB + status + expiry, all timestamps
`datetime.now(timezone.utc)`).

Distinct from Part A: artifacts are *content* (persistent, mostly static);
surfaces are *ephemeral interactive apps* (recipe cook-mode with live timers,
checklists that talk back, file-pickup windows).

## B2. Workspace jobs

Declared, bounded pipelines over existing capabilities ("every email from
Laura in the last 3 days with attachments → pull attachments to a folder"):
`workspace_job` table + small job registry (`email_attachments_fetch`,
`files_collect`) composing `tools/email.py` / `routes/email.py`, running as
Celery tasks, writing to MinIO `workspace/{user_id}/{job_id}/`, live-patching
a `progress` surface that becomes a `file_list` on completion. One completion
notification, dedupe_key = job_id. Downloads stream through
`GET /api/workspace/files/{job_id}/{filename}` (authed, same pattern as A3's
download endpoint).

## B3. Gating (stricter than Part A)

All five layers from the original design:
1. `requires_user_origin = True` on every surface/job tool (hard).
2. **Progressive disclosure**: the `surfaces` tool category is excluded from
   default chat schemas; merged in only when the intent router detects
   explicit construction language ("make a checklist of…", "start cook mode",
   "grab those files").
3. Descriptions open with the ONLY-when-explicitly-asked contract.
4. Proactive systems suggest-only; David's yes opens the gate.
5. `workspace_job_run` states its plan in chat before executing (interruptible;
   escalate to confirm-by-reply if it ever misfires).

## B4. Runtime flow (reference)

- Create: tool → `surface` row → `surface_command` SSE (same forwarding site
  as `canvas_command`, main_simple.py ~1885; Redis mirror for voice) → web
  `custom` view / `command_router.open_surface` for other devices via
  `device_orchestrator` with new `ContentType.SURFACE`.
- Interact: `POST /api/surfaces/{id}/events`; `notify:true` events append a
  compact line to working memory (no standalone LLM call per event;
  `timer_done` rides the existing timer-completion path).
- Teardown: `surface_teardown` tool or direct UI close (UI never needs Sara's
  permission); Celery beat expires stale surfaces; 30-day retention then hard
  delete including job files.

## B5. Part B build order

| Phase | Scope |
|---|---|
| **S1** | `surface` model + spec validation + create/read/update/teardown tools + web `custom` view (`markdown`, `checklist`, `buttons`) + events endpoint |
| **S2** | `steps` + inline `timer` (reuse timer backend) + notify→working-memory |
| **S3** | `workspace_job` + `email_attachments_fetch` + `progress`/`file_list` + download endpoint |
| **S4** | Intent-router progressive disclosure, `form`/`table`, `ContentType.SURFACE` routing, desktop `open_surface`, expiry beat |
| **S5** | iOS renderers |

---

# Shared risks / decisions

- **Model output quality**: closed vocabularies + Pydantic validation with
  corrective errors back through the tool loop (Sara retries in-turn). Same
  class of problem as text-format tool-call salvage — already solved once.
- **No generated HTML/JS** anywhere: unreviewable model code in the app is a
  security/reliability hole and can't render natively on iOS. Markdown in,
  typed JSON or rendered files out.
- **Why not overload `Artifact` for surfaces**: artifacts are content bound to
  conversations; surfaces carry mutable interaction state, expiry, jobs, and
  device routing. Overloading tangles the Studio.
- **Container restarts**: backend/Celery load code at restart only; A-3
  (WeasyPrint) and S3 (Celery job) require rebuilds before verification.
- **Timezones**: storage in `datetime.now(timezone.utc)`; user-facing times
  via `app.core.timezone` ET helpers.
