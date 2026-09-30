from typing import Dict, Any, Optional, Tuple
import logging
import re
from app.tools.base import BaseTool, ToolResult
from app.models.note import Note
from app.models.folder import Folder
from app.services.embeddings import get_embedding
from app.db.session import get_db
from sqlalchemy.orm import Session
from sqlalchemy import text, update as sa_update
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _remove_span(content: str, needle: str) -> Tuple[Optional[str], Optional[str]]:
    """Remove exactly ONE occurrence of `needle` from `content`, touching
    only that occurrence — never reconstructing or rewriting the rest of
    the note. Returns (new_content, error_code); error_code is one of
    "empty", "not_found", "ambiguous" (with a count appended after ':'),
    or None on success.

    R02 (Sara repair plan 2026-09-25 review remediation, evidence
    J03_trial2_TURN6_FALSE_DIAGNOSIS_CAUSES_REAL_DATA_LOSS): the first
    version of this operation deleted the WHOLE LINE containing a match,
    which silently destroyed unrelated text sharing that line — an inline
    comma-separated list item, or a phrase inside a paragraph. This
    replaces that with true span-level removal, matched only at
    non-letter/digit boundaries (so "cup" cannot match inside "cupcake"),
    with three cleanup shapes tried in order:

      1. The match IS an entire line by itself (a list note, one item per
         line) — remove the whole line including its own newline, so no
         blank line is left behind.
      2. The match sits inside a comma-separated inline list ("a, X, b")
         — remove it together with the ONE adjacent ", " separator so the
         list rejoins cleanly, preferring the trailing separator (more
         items follow) and falling back to the leading one (X is last).
      3. Anywhere else (mid-sentence prose) — remove exactly the matched
         characters and collapse a resulting double space. Grammar may
         read slightly awkwardly afterward; no OTHER text is ever altered.

    Exactly one match is required (case-insensitive) — zero or multiple
    matches refuse rather than guess which one was meant.
    """
    if not needle or not needle.strip():
        return None, "empty"

    pattern = re.compile(
        r"(?<![A-Za-z0-9])" + re.escape(needle.strip()) + r"(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(content))
    if not matches:
        return None, "not_found"
    if len(matches) > 1:
        return None, f"ambiguous:{len(matches)}"

    m = matches[0]
    start, end = m.start(), m.end()

    # Shape 1: the match is an entire line by itself.
    line_start = content.rfind("\n", 0, start) + 1
    nl_after = content.find("\n", end)
    line_end = nl_after if nl_after != -1 else len(content)
    if content[line_start:line_end].strip().lower() == needle.strip().lower():
        if nl_after != -1:
            new_content = content[:line_start] + content[nl_after + 1:]
        elif line_start > 0 and content[line_start - 1] == "\n":
            new_content = content[:line_start - 1]
        else:
            new_content = content[:line_start]
        return new_content, None

    # Shape 2: comma-separated inline list item.
    before, after = content[:start], content[end:]
    after_stripped = after.lstrip(" ")
    if after_stripped.startswith(","):
        rest = after_stripped[1:]
        if rest.startswith(" "):
            rest = rest[1:]
        return before + rest, None

    before_rstripped = before.rstrip(" ")
    if before_rstripped.endswith(","):
        new_before = before_rstripped[:-1].rstrip(" ")
        return new_before + after, None

    # Shape 3: plain excision inside prose, collapse any double space.
    new_content = before + after
    new_content = re.sub(r"[ \t]{2,}", " ", new_content)
    return new_content, None


def _resolve_folder(
    db: Session,
    user_id: str,
    folder_id: Optional[str] = None,
    folder_name: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Resolve a folder reference to a folder_id.

    Returns (folder_id, error_message). If both are None, the note belongs at root.
    Accepts either an explicit folder_id or a case-insensitive folder name.
    """
    if folder_id:
        folder = db.query(Folder).filter(
            Folder.id == folder_id,
            Folder.user_id == user_id,
        ).first()
        if not folder:
            return None, f"No folder found with id '{folder_id}'"
        return folder.id, None

    if folder_name:
        name = folder_name.strip().lstrip("/")
        matches = db.query(Folder).filter(
            Folder.user_id == user_id,
            Folder.name.ilike(name),
        ).all()
        if not matches:
            return None, (
                f"No folder named '{folder_name}' exists. "
                "Use notes_create_folder to make one, or notes_list_folders to see existing folders."
            )
        if len(matches) > 1:
            ids = ", ".join(m.id for m in matches)
            return None, (
                f"Multiple folders named '{folder_name}' exist ({ids}). "
                "Pass an explicit folder_id to disambiguate."
            )
        return matches[0].id, None

    return None, None


# --- notes_search result shaping (2026-09-27) -------------------------------
# notes_search used to return every hit's FULL content. Median note in this
# database is 3,977 chars, p90 is 10,732, and the largest is 670,130 — so a
# default limit=10 search routinely produced ~19,000 chars. Anything over
# TOOL_RESULT_INLINE_MAX (9,000) is replaced upstream by `content[:3000]`
# plus "Do not tell David the result was empty", which means hits 3..10 were
# invisible to the model while it was explicitly told not to report an empty
# result. Readback questions therefore got a confident answer drawn from
# whichever note happened to sort first.
#
# A search result only needs to be enough to (a) recognise the right note and
# (b) answer a simple readback. Full content stays one notes_search away with
# a narrower query, or a direct read by note_id.
NOTES_SNIPPET_CHARS = 400

# Below this cosine similarity a note is not a match, it is just the nearest
# row in the table. The vector branch had no floor at all, so a query with no
# real match still returned `limit` arbitrary notes and invited an answer
# assembled from unrelated ones.
NOTES_VECTOR_MIN_SIMILARITY = 0.35

_WORD_RE = re.compile(r"[A-Za-z0-9']+")
# Words that carry no selectivity in a note search. A query like "who did I
# meet from Acme" must search for "acme" (and "meet"), not for the literal
# phrase — the old single whole-query ILIKE matched only notes containing that
# entire sentence, i.e. essentially never.
_NOTE_STOPWORDS = frozenset({
    "a", "an", "and", "any", "are", "about", "at", "be", "but", "by",
    "can", "did", "do", "does", "for", "from", "had", "has", "have", "he",
    "her", "his", "i", "if", "in", "is", "it", "its", "me", "my", "of", "on",
    "or", "our", "she", "that", "the", "their", "them", "then", "there",
    "they", "this", "to", "up", "us", "was", "we", "were", "what", "when",
    "where", "which", "who", "whom", "why", "will", "with", "you", "your",
    "tell", "say", "said", "again", "note", "notes", "anything", "something",
    "remember", "recall", "know", "knew", "meet", "met", "talk", "talked",
})


def _query_terms(query: str, max_terms: int = 6) -> list:
    """Selective search terms from a natural-language query, longest first.

    Longest-first matters: "acme" is a far better filter than "from", and the
    SQL below only uses the first `max_terms` so the discriminating words must
    come first.
    """
    seen = set()
    terms = []
    for w in _WORD_RE.findall(query or ""):
        lw = w.lower()
        if len(lw) < 3 or lw in _NOTE_STOPWORDS or lw in seen:
            continue
        seen.add(lw)
        terms.append(lw)
    terms.sort(key=len, reverse=True)
    return terms[:max_terms]


def _snippet(content: Optional[str], terms: Optional[list] = None,
             width: int = NOTES_SNIPPET_CHARS) -> str:
    """A short excerpt, centred on the first matching term when there is one.

    The point of centring is that the reason a note matched should be visible
    in the excerpt — a person's name three paragraphs in is exactly the case
    that a leading `content[:400]` would hide.
    """
    text_val = (content or "").strip()
    if len(text_val) <= width:
        return text_val

    start = 0
    if terms:
        low = text_val.lower()
        positions = [p for p in (low.find(t) for t in terms) if p != -1]
        if positions:
            start = max(0, min(positions) - width // 3)

    excerpt = text_val[start:start + width].strip()
    prefix = "…" if start > 0 else ""
    suffix = "…" if start + width < len(text_val) else ""
    return f"{prefix}{excerpt}{suffix}"


def _subject_key(title: Optional[str]) -> frozenset:
    """The distinctive words of a note's title, as its subject identity.

    Uses the same word normalization the reference resolver uses, so "Priya
    Raghavan" and "Priya Raghavan (Initech)" are one subject while "Priya's
    cactus" is not.
    """
    from app.services.reference_resolution import distinctive_words

    return distinctive_words(title)


def _same_subject_note(db: Session, user_id: str, title: Optional[str]):
    """One of David's existing notes about the same subject, or None.

    Only a title whose distinctive words are a subset of (or equal to) the new
    title's — and at least one word — counts. A titleless note never matches,
    and neither does a note whose title shares only stopwords.
    """
    key = _subject_key(title)
    if not key:
        return None
    candidates = (
        db.query(Note)
        .filter(Note.user_id == user_id, Note.title.isnot(None), Note.title != "")
        .order_by(Note.created_at.desc())
        .limit(200)
        .all()
    )
    for note in candidates:
        other = _subject_key(note.title)
        if not other:
            continue
        if other == key or other <= key or key <= other:
            return note
    return None


class NotesCreateTool(BaseTool):
    """Tool for creating new notes"""
    
    @property
    def name(self) -> str:
        return "notes_create"
    
    @property
    def description(self) -> str:
        return (
            "Create a NEW note with optional title and content. The note will be "
            "automatically embedded for semantic search.\n"
            "Do NOT use this to correct or update something already written down. If a "
            "note on this subject already exists — you searched and found one, or you "
            "wrote one earlier in this conversation — call notes_edit with append_text "
            "on THAT note instead. Two notes disagreeing about the same person is worse "
            "than one note carrying its own correction: a later search can surface the "
            "stale one and answer David wrongly."
        )
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Optional title for the note"
                },
                "content": {
                    "type": "string",
                    "description": "The note content"
                },
                "folder_name": {
                    "type": "string",
                    "description": "Optional folder name to file the note under (e.g. 'Recipes'). The folder must already exist; use notes_create_folder first if needed."
                },
                "folder_id": {
                    "type": "string",
                    "description": "Optional explicit folder ID. Prefer folder_name unless disambiguating duplicates."
                }
            },
            "required": ["content"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Create a new note"""

        title = kwargs.get("title", "")
        content = kwargs.get("content")
        folder_id_arg = kwargs.get("folder_id")
        folder_name_arg = kwargs.get("folder_name")

        if not content:
            return ToolResult(
                success=False,
                message="Note content is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # ── Same-subject guard (reliable-assistant plan, 2026-09-29) ──────
            #
            # Found live on the acceptance trial's first journey: capturing two
            # people in two turns produced THREE notes — a second note about
            # Priya, duplicating the first. Finding 32 is the same shape
            # ("silent duplicate object creation (a note), 3rd instance of this
            # pattern"), and the tool description already asked the model not to
            # do it, which is exactly the kind of instruction that does not
            # hold. A subject is a thing David has one note about; the
            # application can check that.
            #
            # Deliberately narrow: only a note whose title has the SAME
            # distinctive words (so "Priya Raghavan" and "Priya Raghavan
            # (Initech)" are the same subject, "Priya's cactus" is not), and it
            # APPENDS rather than refusing — the capture still lands, which is
            # what David asked for, and nothing is lost either way.
            existing = _same_subject_note(db, user_id, title)
            if existing is not None:
                appended = (existing.content or "").rstrip() + "\n" + content
                new_updated_at = datetime.now(timezone.utc)
                db.execute(sa_update(Note).where(
                    Note.id == existing.id, Note.user_id == user_id,
                ).values(
                    content=appended,
                    updated_at=new_updated_at,
                    embedding=await get_embedding(
                        f"{existing.title}\n{appended}" if existing.title else appended),
                ))
                db.commit()
                logger.info(
                    "📝 notes_create appended to the existing note for this "
                    "subject instead of creating a duplicate: %s", existing.title,
                )
                return ToolResult(
                    success=True,
                    data={
                        "note_id": str(existing.id),
                        "title": existing.title,
                        "content": appended,
                        "appended_to_existing": True,
                        "updated_at": new_updated_at.isoformat(),
                    },
                    message=(
                        f"Added that to the existing \"{existing.title}\" note rather "
                        f"than starting a second one about the same thing."
                    ),
                )

            # Resolve target folder (by id or name) if one was requested
            resolved_folder_id, folder_err = _resolve_folder(
                db, user_id, folder_id_arg, folder_name_arg
            )
            if folder_err:
                return ToolResult(success=False, message=folder_err)

            # Get embedding for the note
            full_text = f"{title}\n{content}" if title else content
            embedding = await get_embedding(full_text)

            # Create note
            note = Note(
                user_id=user_id,
                title=title,
                content=content,
                folder_id=resolved_folder_id,
                embedding=embedding
            )

            db.add(note)
            db.commit()
            db.refresh(note)

            # Detect connections (wiki links + semantic neighbors)
            try:
                from app.services.note_connector import process_note_connections_sync
                await process_note_connections_sync(
                    str(note.id), user_id, title, content, db
                )
            except Exception as conn_err:
                logger.warning(f"Connection detection failed for new note: {conn_err}")

            return ToolResult(
                success=True,
                data={
                    "note_id": str(note.id),
                    "title": note.title,
                    "content": note.content,
                    "folder_id": note.folder_id,
                    "created_at": note.created_at.isoformat()
                },
                message=(
                    f"Created note: {title or 'Untitled'}"
                    + (f" (in folder {folder_name_arg or resolved_folder_id})" if resolved_folder_id else "")
                )
            )
            
        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to create note: {str(e)}"
            )
        finally:
            db.close()


class NotesSearchTool(BaseTool):
    """Tool for searching notes"""
    
    @property
    def name(self) -> str:
        return "notes_search"
    
    @property
    def description(self) -> str:
        return (
            "Search the user's notes by keyword and semantic similarity. Returns the "
            "best matches as EXCERPTS (a few hundred characters each) with note_id, "
            "title and dates — not whole notes. If an excerpt looks like the right "
            "note but you need more of it, search again with a narrower query drawn "
            "from that note's own wording. An empty result means nothing matched: say "
            "so rather than answering from memory."
        )
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for finding notes"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of notes to return (default: 10)",
                    "default": 10
                }
            },
            "required": ["query"]
        }
    
    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Search notes using text matching (title/content) with vector similarity as secondary"""

        query = kwargs.get("query")
        limit = kwargs.get("limit", 10)

        if not query:
            return ToolResult(
                success=False,
                message="Search query is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            notes = []
            citations = []
            seen_ids = set()

            # Normalize query for fuzzy matching (remove spaces)
            normalized_query = query.replace(" ", "")
            terms = _query_terms(query)

            # FIRST: Text-based search on title and content (works even without
            # embeddings). The whole query is still tried as one phrase — that
            # is the strongest possible signal when it hits — but a natural
            # question ("who did I meet from Acme?") only ever matches on its
            # individual terms, so those are tried too, ranked by how many of
            # them a note actually contains.
            term_patterns = {f"t{i}": f"%{t}%" for i, t in enumerate(terms)}
            if term_patterns:
                term_where = " OR ".join(
                    f"(title ILIKE :{k} OR content ILIKE :{k})" for k in term_patterns
                )
                term_score = " + ".join(
                    f"(CASE WHEN title ILIKE :{k} THEN 2 "
                    f"WHEN content ILIKE :{k} THEN 1 ELSE 0 END)"
                    for k in term_patterns
                )
            else:
                term_where = "FALSE"
                term_score = "0"

            text_sql = text(f"""
                SELECT id, title, content, created_at, updated_at,
                       ({term_score}) AS term_score,
                       (CASE WHEN title ILIKE :query_pattern THEN 1 ELSE 0 END) AS phrase_title,
                       (CASE WHEN content ILIKE :query_pattern THEN 1 ELSE 0 END) AS phrase_body
                FROM note
                WHERE user_id = :user_id
                  AND (
                    title ILIKE :query_pattern
                    OR REPLACE(title, ' ', '') ILIKE :normalized_pattern
                    OR content ILIKE :query_pattern
                    OR ({term_where})
                  )
                ORDER BY
                    phrase_title DESC,
                    term_score DESC,
                    phrase_body DESC,
                    updated_at DESC
                LIMIT :limit
            """)

            text_result = db.execute(text_sql, {
                "user_id": user_id,
                "query_pattern": f"%{query}%",
                "normalized_pattern": f"%{normalized_query}%",
                "limit": limit,
                **term_patterns,
            })

            for row in text_result.fetchall():
                if str(row.id) not in seen_ids:
                    seen_ids.add(str(row.id))
                    notes.append({
                        "note_id": str(row.id),
                        "title": row.title,
                        "snippet": _snippet(row.content, terms),
                        "content_chars": len(row.content or ""),
                        "match": "text",
                        "created_at": row.created_at.isoformat(),
                        "updated_at": row.updated_at.isoformat()
                    })
                    citations.append(f"note:{row.id}")

            # SECOND: If we need more results, add vector similarity search
            if len(notes) < limit:
                try:
                    query_embedding = await get_embedding(query)

                    vector_sql = text("""
                        SELECT
                            id, title, content, created_at, updated_at,
                            (1 - (embedding <=> :query_embedding)) as similarity
                        FROM note
                        WHERE user_id = :user_id AND embedding IS NOT NULL
                        ORDER BY (embedding <=> :query_embedding)
                        LIMIT :limit
                    """)

                    vector_result = db.execute(vector_sql, {
                        "query_embedding": str(query_embedding),
                        "user_id": user_id,
                        "limit": limit
                    })

                    for row in vector_result.fetchall():
                        if str(row.id) in seen_ids or len(notes) >= limit:
                            continue
                        # Nearest-neighbour with no floor returned `limit`
                        # arbitrary notes whenever nothing actually matched,
                        # which is how an answer gets assembled out of
                        # unrelated notes. Below the floor it is not a match.
                        if row.similarity is None or row.similarity < NOTES_VECTOR_MIN_SIMILARITY:
                            continue
                        seen_ids.add(str(row.id))
                        notes.append({
                            "note_id": str(row.id),
                            "title": row.title,
                            "snippet": _snippet(row.content, terms),
                            "content_chars": len(row.content or ""),
                            "match": "semantic",
                            "similarity": round(row.similarity, 3),
                            "created_at": row.created_at.isoformat(),
                            "updated_at": row.updated_at.isoformat()
                        })
                        citations.append(f"note:{row.id}")
                except Exception as embed_error:
                    # Vector search failed, but text search may have worked
                    logger.warning(f"notes_search vector branch failed: {type(embed_error).__name__}: {embed_error}")

            if notes:
                message = (
                    f"Found {len(notes)} notes matching '{query}'. Each result is an "
                    "excerpt, not the whole note — search again with a narrower query "
                    "if you need more of one."
                )
            else:
                message = (
                    f"No notes matched '{query}'. Nothing was found — say so rather "
                    "than answering from memory."
                )

            return ToolResult(
                success=True,
                data={
                    "notes": notes,
                    "query": query,
                    "total_found": len(notes)
                },
                message=message,
                citations=citations
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Note search failed: {str(e)}"
            )
        finally:
            db.close()


class NotesEditTool(BaseTool):
    """Tool for editing existing notes"""
    
    @property
    def name(self) -> str:
        return "notes_edit"
    
    @property
    def description(self) -> str:
        return (
            "Edit an existing note's title or content. The note will be re-embedded after editing. "
            "CORRECTING A FACT ('actually she's at Initech, not Globex', 'his title is VP') "
            "→ use `notes_correct_fact` instead. It updates the stale value everywhere it is "
            "stated as current, including the title, keeps the previous value in the note's "
            "History section, and leaves dated historical lines accurate. Do NOT use content "
            "or title here for a correction (that rewrites or renames the whole note), and do "
            "not append a contradiction — a note whose title still says Globex reads wrong at "
            "a glance forever.\n"
            "For removing or adding ONE item from an otherwise-unchanged note (e.g. 'remove the "
            "rain jacket but keep the other items'), use remove_text or append_text instead of content "
            "— they touch only the matched text (a whole line, one item in a comma-separated list, or "
            "a phrase mid-sentence) and leave everything else byte-for-byte untouched. Use content only "
            "for a genuine full rewrite, and pass base_revision (the updated_at you last read for this "
            "note) with it — this refuses instead of overwriting if the note changed since you last saw it."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": "The ID of the note to edit"
                },
                "title": {
                    "type": "string",
                    "description": "New title for the note"
                },
                "content": {
                    "type": "string",
                    "description": (
                        "Full replacement content for the note — REPLACES everything. Do not use "
                        "this for a narrow single-item change ('remove X', 'add Y'); use remove_text "
                        "or append_text for those so unrelated existing content can't be silently lost. "
                        "Requires base_revision if the note currently has content."
                    )
                },
                "base_revision": {
                    "type": "string",
                    "description": (
                        "The note's updated_at timestamp as you last read it (from notes_search, "
                        "notes_list, or a prior notes_edit result). Required when using content on a "
                        "note that already has content — if the note changed since then, the edit is "
                        "refused instead of silently overwriting the newer version; reread and retry."
                    )
                },
                "remove_text": {
                    "type": "string",
                    "description": (
                        "Remove exactly the one existing occurrence of this text — a whole line, one "
                        "item in a comma-separated list, or a phrase mid-sentence — leaving every other "
                        "line/item/word untouched. Fails honestly (no change made) if the text isn't "
                        "found or matches more than once — it never guesses. Mutually exclusive with content."
                    )
                },
                "append_text": {
                    "type": "string",
                    "description": "Add this as a new line at the end of the note's existing content, leaving everything else untouched. Mutually exclusive with content.",
                },
                "folder_name": {
                    "type": "string",
                    "description": "Optional: move the note into this folder (by name). The folder must already exist."
                },
                "folder_id": {
                    "type": "string",
                    "description": "Optional: move the note into this folder (by explicit ID). Pass 'root' to move the note out of any folder."
                }
            },
            "required": ["note_id"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Edit an existing note.

        R02 (Sara repair plan 2026-09-25 review remediation): every write
        path here (title, content, remove_text, append_text, folder move)
        now goes through ONE conditional UPDATE, guarded by the note's
        `updated_at` at the moment this call read it — not the ORM's
        implicit "last write wins" commit. If any other write (another
        session, another tool call, a concurrent request) committed to
        this note between this call's read and its write, the conditional
        UPDATE matches zero rows and the whole edit is refused rather than
        silently clobbering whatever that other write did. This is
        automatic and requires no cooperation from the caller. `content`
        additionally requires an explicit `base_revision` argument when
        the note has existing content — forcing the caller to have looked
        at a specific revision before requesting a full rewrite, which the
        automatic same-call check alone cannot guarantee (it only proves
        nothing else committed in the brief window of THIS call, not that
        the caller's belief about the content is actually current).
        """

        note_id = kwargs.get("note_id")
        new_title = kwargs.get("title")
        new_content = kwargs.get("content")
        base_revision = kwargs.get("base_revision")
        remove_text = kwargs.get("remove_text")
        append_text = kwargs.get("append_text")
        folder_id_arg = kwargs.get("folder_id")
        folder_name_arg = kwargs.get("folder_name")

        if not note_id:
            return ToolResult(
                success=False,
                message="Note ID is required"
            )

        # content and remove_text/append_text are different operations on
        # the same field — mixing them makes the intended result ambiguous
        # (does a full replacement happen before or after the line
        # removal?), so refuse rather than guess an order.
        if new_content is not None and (remove_text is not None or append_text is not None):
            return ToolResult(
                success=False,
                message="Pass either content (full replacement) or remove_text/append_text (single-line edit), not both.",
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Find the note
            note = db.query(Note).filter(
                Note.id == note_id,
                Note.user_id == user_id
            ).first()

            if not note:
                return ToolResult(
                    success=False,
                    message="Note not found"
                )

            # Captured immediately after the read above — this is the
            # revision the conditional UPDATE below is staked against.
            read_updated_at = note.updated_at
            current_content = note.content or ""

            if new_content is not None and current_content:
                current_revision = read_updated_at.isoformat() if read_updated_at else None
                if base_revision is None:
                    return ToolResult(
                        success=False,
                        message=(
                            "This note already has content — a full replacement needs base_revision "
                            f"(the updated_at you last read: {current_revision}) so a stale rewrite "
                            "can be refused instead of silently overwriting it. If you haven't actually "
                            "read this note's current content, do that first."
                        ),
                    )
                if base_revision != current_revision:
                    return ToolResult(
                        success=False,
                        message=(
                            "This note has changed since the revision you gave — reread its current "
                            "content before overwriting it, so you don't drop whatever changed."
                        ),
                    )

            values: Dict[str, Any] = {}
            final_title = new_title if new_title is not None else note.title
            final_content = current_content

            if new_title is not None:
                values["title"] = new_title

            if new_content is not None:
                final_content = new_content
                values["content"] = new_content

            # R02: narrow, span-level operations. Never reconstruct the
            # rest of the content from the model's own belief about what
            # the note contains — J03's real failure was a full-content
            # rewrite built on a FALSE belief that an earlier item was
            # never saved (it was), which silently dropped that item even
            # though the user only asked to remove a different one. These
            # touch exactly the matched span (or append a new line) and
            # leave everything else byte-for-byte as stored — see
            # _remove_span's docstring for the three removal shapes.
            if remove_text is not None:
                new_span_content, err = _remove_span(current_content, remove_text)
                if err == "empty":
                    return ToolResult(success=False, message="remove_text is empty — nothing to remove.")
                if err == "not_found":
                    return ToolResult(
                        success=False,
                        message=(
                            f"Didn't find \"{remove_text}\" in the note's current content — nothing "
                            "removed. Reread the note first if you're not sure what's actually in it."
                        ),
                    )
                if err and err.startswith("ambiguous"):
                    count = err.split(":", 1)[1]
                    return ToolResult(
                        success=False,
                        message=(
                            f"\"{remove_text}\" appears {count} separate times in the note — too "
                            "ambiguous to remove automatically. Say exactly which occurrence, or pass "
                            "the full replacement via content."
                        ),
                    )
                final_content = new_span_content
                values["content"] = new_span_content

            if append_text is not None:
                stripped = append_text.strip()
                if not stripped:
                    return ToolResult(success=False, message="append_text is empty — nothing to add.")
                final_content = (
                    current_content + ("\n" if current_content and not current_content.endswith("\n") else "")
                    + append_text
                )
                values["content"] = final_content

            # Optional folder move
            final_folder_id = note.folder_id
            if folder_id_arg is not None and folder_id_arg.lower() in ("root", "none", ""):
                final_folder_id = None
                values["folder_id"] = None
            elif folder_id_arg or folder_name_arg:
                resolved_folder_id, folder_err = _resolve_folder(
                    db, user_id, folder_id_arg, folder_name_arg
                )
                if folder_err:
                    return ToolResult(success=False, message=folder_err)
                final_folder_id = resolved_folder_id
                values["folder_id"] = resolved_folder_id

            if not values:
                return ToolResult(
                    success=False,
                    message="No changes provided"
                )

            # Re-embed against the FINAL title/content this call is about
            # to write, not the pre-edit ones.
            full_text = f"{final_title}\n{final_content}" if final_title else final_content
            values["embedding"] = await get_embedding(full_text)
            new_updated_at = datetime.now(timezone.utc)
            values["updated_at"] = new_updated_at

            # The conditional UPDATE itself — this is what makes a
            # concurrent edit safe without needing the caller to
            # cooperate: it only applies if updated_at is EXACTLY what
            # this call observed when it read the note above.
            where_clause = [Note.id == note_id, Note.user_id == user_id]
            if read_updated_at is None:
                where_clause.append(Note.updated_at.is_(None))
            else:
                where_clause.append(Note.updated_at == read_updated_at)

            stmt = sa_update(Note).where(*where_clause).values(**values)
            result = db.execute(stmt)

            if result.rowcount == 0:
                db.rollback()
                return ToolResult(
                    success=False,
                    message=(
                        "This note changed since this edit started (a concurrent edit committed first) "
                        "— nothing was written. Reread the note's current content and reissue the edit "
                        "against that."
                    ),
                )

            db.commit()

            # Re-detect connections after edit
            try:
                from app.services.note_connector import process_note_connections_sync
                await process_note_connections_sync(
                    str(note_id), user_id, final_title or "", final_content or "", db
                )
            except Exception as conn_err:
                logger.warning(f"Connection detection failed for edited note: {conn_err}")

            return ToolResult(
                success=True,
                data={
                    "note_id": str(note_id),
                    "title": final_title,
                    "content": final_content,
                    "updated_at": new_updated_at.isoformat()
                },
                message=f"Updated note: {final_title or 'Untitled'}"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to edit note: {str(e)}"
            )
        finally:
            db.close()


class NotesDeleteTool(BaseTool):
    """Tool for deleting notes"""

    @property
    def name(self) -> str:
        return "notes_delete"

    @property
    def description(self) -> str:
        return "Delete a note by its ID. This action cannot be undone."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": "The ID of the note to delete"
                }
            },
            "required": ["note_id"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Delete a note"""

        note_id = kwargs.get("note_id")

        if not note_id:
            return ToolResult(
                success=False,
                message="Note ID is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Find the note
            note = db.query(Note).filter(
                Note.id == note_id,
                Note.user_id == user_id
            ).first()

            if not note:
                return ToolResult(
                    success=False,
                    message="Note not found"
                )

            # Store title for response message
            note_title = note.title or "Untitled"

            # Delete the note
            db.delete(note)
            db.commit()

            return ToolResult(
                success=True,
                data={
                    "note_id": note_id,
                    "deleted_title": note_title
                },
                message=f"Deleted note: {note_title}"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to delete note: {str(e)}"
            )
        finally:
            db.close()


class NotesListTool(BaseTool):
    """Tool for listing all notes"""

    @property
    def name(self) -> str:
        return "notes_list"

    @property
    def description(self) -> str:
        return "List all notes for the user, optionally filtered by folder. Returns note IDs, titles, and preview of content."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "folder_id": {
                    "type": "string",
                    "description": "Optional folder ID to filter notes by folder"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of notes to return (default: 20)",
                    "default": 20
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """List all notes"""

        folder_id = kwargs.get("folder_id")
        limit = kwargs.get("limit", 20)

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Build query
            query = db.query(Note).filter(Note.user_id == user_id)

            if folder_id:
                query = query.filter(Note.folder_id == folder_id)

            # Order by most recent first
            query = query.order_by(Note.updated_at.desc()).limit(limit)

            notes = query.all()

            # Format results
            notes_list = []
            citations = []
            for note in notes:
                # Preview first 100 chars of content
                content_preview = note.content[:100] + "..." if len(note.content) > 100 else note.content

                notes_list.append({
                    "note_id": str(note.id),
                    "title": note.title or "Untitled",
                    "content_preview": content_preview,
                    "folder_id": note.folder_id,
                    "created_at": note.created_at.isoformat(),
                    "updated_at": note.updated_at.isoformat()
                })
                citations.append(f"note:{note.id}")

            return ToolResult(
                success=True,
                data={
                    "notes": notes_list,
                    "total": len(notes_list),
                    "folder_id": folder_id
                },
                message=f"Found {len(notes_list)} note(s)",
                citations=citations
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to list notes: {str(e)}"
            )
        finally:
            db.close()


class NotesFindSimilarTool(BaseTool):
    """Tool for finding semantically similar notes."""

    @property
    def name(self) -> str:
        return "find_similar_notes"

    @property
    def description(self) -> str:
        return (
            "Find notes that are semantically similar, useful for discovering "
            "redundancy or connections. Excludes journal entries."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": "Optional: find notes similar to this specific note",
                },
                "threshold": {
                    "type": "number",
                    "description": "Minimum similarity (0.0-1.0, default 0.78)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 10)",
                },
            },
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        note_id = kwargs.get("note_id")
        threshold = kwargs.get("threshold", 0.78)
        limit = kwargs.get("limit", 10)

        db = next(get_db())
        try:
            if note_id:
                result = db.execute(
                    text("""
                        SELECT n2.id, n2.title, LEFT(n2.content, 200) AS preview,
                               1 - (n1.embedding <=> n2.embedding) AS similarity
                        FROM note n1
                        JOIN note n2 ON n2.user_id = n1.user_id
                            AND n2.id != n1.id
                            AND n2.embedding IS NOT NULL
                            AND n2.title NOT LIKE 'Sara''s Journal%%'
                        WHERE n1.id = :nid AND n1.embedding IS NOT NULL
                          AND 1 - (n1.embedding <=> n2.embedding) > :threshold
                        ORDER BY similarity DESC
                        LIMIT :lim
                    """),
                    {"nid": note_id, "threshold": threshold, "lim": limit},
                )
                notes = [
                    {
                        "note_id": str(r[0]),
                        "title": r[1],
                        "content_preview": r[2],
                        "similarity": round(float(r[3]), 3),
                    }
                    for r in result.fetchall()
                ]
            else:
                result = db.execute(
                    text("""
                        SELECT n1.id, n1.title, LEFT(n1.content, 200),
                               n2.id, n2.title, LEFT(n2.content, 200),
                               1 - (n1.embedding <=> n2.embedding) AS similarity
                        FROM note n1
                        JOIN note n2 ON n2.user_id = n1.user_id
                            AND n2.id > n1.id
                            AND n2.embedding IS NOT NULL
                            AND n2.title NOT LIKE 'Sara''s Journal%%'
                        WHERE n1.user_id = :uid
                          AND n1.embedding IS NOT NULL
                          AND n1.title NOT LIKE 'Sara''s Journal%%'
                          AND 1 - (n1.embedding <=> n2.embedding) > :threshold
                        ORDER BY similarity DESC
                        LIMIT :lim
                    """),
                    {"uid": user_id, "threshold": threshold, "lim": limit},
                )
                notes = [
                    {
                        "note_a": {"note_id": str(r[0]), "title": r[1], "preview": r[2]},
                        "note_b": {"note_id": str(r[3]), "title": r[4], "preview": r[5]},
                        "similarity": round(float(r[6]), 3),
                    }
                    for r in result.fetchall()
                ]

            return ToolResult(
                success=True,
                data={"results": notes, "total": len(notes)},
                message=f"Found {len(notes)} similar note{'s' if len(notes) != 1 else ''} (threshold={threshold})",
            )
        except Exception as e:
            return ToolResult(success=False, message=f"Failed to find similar notes: {e}")
        finally:
            db.close()


class NotesMergeTool(BaseTool):
    """Tool for merging two overlapping notes into one."""

    @property
    def name(self) -> str:
        return "merge_notes"

    @property
    def description(self) -> str:
        return (
            "Merge two overlapping notes. Transfers connections from source to target, "
            "deletes source, updates target with synthesized content."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target_note_id": {
                    "type": "string",
                    "description": "The note to keep (updated with merged content)",
                },
                "source_note_id": {
                    "type": "string",
                    "description": "The note to merge in and delete",
                },
                "merged_title": {
                    "type": "string",
                    "description": "Optional new title for the merged note",
                },
                "merged_content": {
                    "type": "string",
                    "description": "Synthesized content combining both notes",
                },
            },
            "required": ["target_note_id", "source_note_id", "merged_content"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        target_id = kwargs.get("target_note_id", "")
        source_id = kwargs.get("source_note_id", "")
        merged_title = kwargs.get("merged_title")
        merged_content = kwargs.get("merged_content", "")

        if not target_id or not source_id or not merged_content:
            return ToolResult(
                success=False,
                message="target_note_id, source_note_id, and merged_content are required",
            )

        db = next(get_db())
        try:
            # Verify both notes exist
            target = db.query(Note).filter(Note.id == target_id, Note.user_id == user_id).first()
            source = db.query(Note).filter(Note.id == source_id, Note.user_id == user_id).first()
            if not target:
                return ToolResult(success=False, message=f"Target note {target_id} not found")
            if not source:
                # Source already deleted (likely merged in a previous call) — skip gracefully
                return ToolResult(
                    success=True,
                    message=f"Source note {source_id} already deleted or merged — nothing to do. Move on to the next pair.",
                )

            source_title = source.title

            # Transfer connections from source to target
            db.execute(
                text("""
                    UPDATE note_connection
                    SET source_note_id = :tid, updated_at = NOW()
                    WHERE source_note_id = :sid AND user_id = :uid
                      AND target_note_id != :tid
                      AND NOT EXISTS (
                          SELECT 1 FROM note_connection nc2
                          WHERE nc2.source_note_id = :tid
                            AND nc2.target_note_id = note_connection.target_note_id
                            AND nc2.connection_type = note_connection.connection_type
                      )
                """),
                {"tid": target_id, "sid": source_id, "uid": user_id},
            )
            db.execute(
                text("""
                    UPDATE note_connection
                    SET target_note_id = :tid, updated_at = NOW()
                    WHERE target_note_id = :sid AND user_id = :uid
                      AND source_note_id != :tid
                      AND NOT EXISTS (
                          SELECT 1 FROM note_connection nc2
                          WHERE nc2.target_note_id = :tid
                            AND nc2.source_note_id = note_connection.source_note_id
                            AND nc2.connection_type = note_connection.connection_type
                      )
                """),
                {"tid": target_id, "sid": source_id, "uid": user_id},
            )

            # Delete source note
            db.delete(source)

            # Update target
            if merged_title:
                target.title = merged_title
            target.content = merged_content
            target.updated_at = datetime.now(timezone.utc)

            # Re-embed
            full_text = f"{target.title}\n{merged_content}" if target.title else merged_content
            target.embedding = await get_embedding(full_text)

            db.commit()

            # Detect new connections
            try:
                from app.services.note_connector import process_note_connections_sync
                await process_note_connections_sync(
                    target_id, user_id, target.title or "", merged_content, db
                )
            except Exception as e:
                logger.warning(f"Connection detection after merge failed: {e}")

            return ToolResult(
                success=True,
                data={
                    "merged_note_id": target_id,
                    "title": target.title,
                    "deleted_source": source_title,
                },
                message=f"Merged '{source_title}' into '{target.title}'",
            )
        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to merge notes: {e}")
        finally:
            db.close()


class NotesListFoldersTool(BaseTool):
    """Tool for listing the user's note folders."""

    @property
    def name(self) -> str:
        return "notes_list_folders"

    @property
    def description(self) -> str:
        return (
            "List the folders in the knowledge garden, with their IDs, full paths, "
            "and note counts. Use this to discover folder IDs before filing or listing "
            "notes in a folder."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            folders = db.query(Folder).filter(
                Folder.user_id == user_id
            ).order_by(Folder.name).all()

            # Build id->name map for path resolution
            by_id = {f.id: f for f in folders}

            def full_path(folder: Folder) -> str:
                parts = [folder.name]
                seen = {folder.id}
                parent_id = folder.parent_id
                while parent_id and parent_id in by_id and parent_id not in seen:
                    seen.add(parent_id)
                    parent = by_id[parent_id]
                    parts.append(parent.name)
                    parent_id = parent.parent_id
                return "/" + "/".join(reversed(parts))

            folder_list = []
            for f in folders:
                note_count = db.query(Note).filter(Note.folder_id == f.id).count()
                folder_list.append({
                    "folder_id": f.id,
                    "name": f.name,
                    "path": full_path(f),
                    "parent_id": f.parent_id,
                    "notes_count": note_count,
                })

            return ToolResult(
                success=True,
                data={"folders": folder_list, "total": len(folder_list)},
                message=(
                    f"Found {len(folder_list)} folder(s)"
                    if folder_list else
                    "No folders yet — the knowledge garden has no folders. Use notes_create_folder to make one."
                ),
            )
        except Exception as e:
            return ToolResult(success=False, message=f"Failed to list folders: {e}")
        finally:
            db.close()


class NotesCreateFolderTool(BaseTool):
    """Tool for creating a note folder."""

    @property
    def name(self) -> str:
        return "notes_create_folder"

    @property
    def description(self) -> str:
        return (
            "Create a new folder in the knowledge garden. Optionally nest it under an "
            "existing parent folder. Returns the new folder's ID so notes can be filed into it. "
            "If a folder with the same name already exists under the same parent, the existing "
            "one is returned instead of creating a duplicate."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the new folder",
                },
                "parent_folder_name": {
                    "type": "string",
                    "description": "Optional name of an existing folder to nest this one under",
                },
                "parent_folder_id": {
                    "type": "string",
                    "description": "Optional explicit parent folder ID (prefer parent_folder_name)",
                },
            },
            "required": ["name"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        name = (kwargs.get("name") or "").strip()
        parent_id_arg = kwargs.get("parent_folder_id")
        parent_name_arg = kwargs.get("parent_folder_name")

        if not name:
            return ToolResult(success=False, message="Folder name is required")

        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            # Resolve parent folder if requested
            parent_id, parent_err = _resolve_folder(
                db, user_id, parent_id_arg, parent_name_arg
            )
            if parent_err:
                return ToolResult(success=False, message=parent_err)

            # Dedupe: same name under same parent → return existing
            existing = db.query(Folder).filter(
                Folder.user_id == user_id,
                Folder.name.ilike(name),
                Folder.parent_id == parent_id,
            ).first()
            if existing:
                return ToolResult(
                    success=True,
                    data={
                        "folder_id": existing.id,
                        "name": existing.name,
                        "parent_id": existing.parent_id,
                        "already_existed": True,
                    },
                    message=f"Folder '{name}' already exists — using it.",
                )

            folder = Folder(name=name, parent_id=parent_id, user_id=user_id)
            db.add(folder)
            db.commit()
            db.refresh(folder)

            return ToolResult(
                success=True,
                data={
                    "folder_id": folder.id,
                    "name": folder.name,
                    "parent_id": folder.parent_id,
                    "already_existed": False,
                },
                message=f"Created folder: {name}",
            )
        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to create folder: {e}")
        finally:
            db.close()

# ---------------------------------------------------------------------------
# Fact correction — reliable-assistant plan Phase E
# ---------------------------------------------------------------------------
#
# "Create one clear user-facing route for remembering and correcting
# information… Resolve the entity/fact or note being corrected. Update current
# truth, preserve provenance/history, and refresh indexes and relevant
# titles/summaries… Do not make appended contradictions the final memory
# architecture."
#
# What existed before this: `notes_edit(append_text=…)` with a dated line. It
# worked, and the 2026-09-27 convention run recorded exactly what it costs —
# the stored note ended as
#
#     title    | Priya Raghavan — Globex
#     content  | Priya Raghavan is at Globex. …
#              | Correction 2026-09-27: Priya Raghavan is now at Initech, not Globex.
#
# so the note's TITLE and its first line still asserted the stale fact, and
# every later read had to notice the correction line to answer correctly. The
# readiness report listed that as a live caveat ("a future search still
# surfaces a note *titled* Globex"), and the review called appended
# contradictions "not a general solution for editing existing facts".
#
# The alternative the gate forced at the time was a full `content` rewrite,
# which is what destroyed a real item in J03 (a rewrite built on a false belief
# that an earlier addition never happened). So this is deliberately neither: a
# bounded, counted substitution of one value for another, revision-checked,
# with the prior value preserved in the note's own History section.
#
# Historical statements are left alone on purpose. "Priya moved companies"
# must not falsify the record of a meeting that really did happen at Globex
# (plan E: "distinguish a historical fact from an error"), so a line that
# starts with a date, or sits under the History heading, keeps its original
# wording and is reported as left untouched.

_HISTORY_HEADING = "## History"

# A line that opens with a date is a record of something that happened then.
# Matched narrowly — ISO, "Sep 27", "9/27" — at the very start of a line only.
_DATED_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:"
    r"\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}/\d{1,2}(?:/\d{2,4})?"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}"
    r")\b",
    re.IGNORECASE,
)


def _split_history(content: str) -> Tuple[str, str]:
    """(body, history) — history includes its heading, or is empty."""
    idx = content.find(_HISTORY_HEADING)
    if idx == -1:
        return content, ""
    return content[:idx].rstrip(), content[idx:]


def substitute_current_fact(
    content: str, old_value: str, new_value: str,
) -> Tuple[str, int, int]:
    """Replace `old_value` with `new_value` in the note's CURRENT-fact lines.

    Returns (new_content, replaced, left_historical). Case-insensitive
    matching, original casing of the replacement preserved as given. Dated
    lines and anything under the History heading are never touched.
    """
    body, history = _split_history(content or "")
    pattern = re.compile(re.escape(old_value), re.IGNORECASE)

    replaced = 0
    left_historical = 0
    out_lines = []
    for line in body.split("\n"):
        hits = len(pattern.findall(line))
        if not hits:
            out_lines.append(line)
            continue
        if _DATED_LINE_RE.match(line):
            left_historical += hits
            out_lines.append(line)
            continue
        out_lines.append(pattern.sub(new_value, line))
        replaced += hits

    new_body = "\n".join(out_lines)
    left_historical += len(pattern.findall(history))
    return (new_body + ("\n\n" + history if history else "")), replaced, left_historical


def append_history_line(content: str, line: str) -> str:
    """Add one line under the note's History heading, creating it if needed."""
    body, history = _split_history(content or "")
    if not history:
        history = _HISTORY_HEADING
    history = history.rstrip() + "\n" + line
    return (body.rstrip() + "\n\n" + history).strip()


class NotesCorrectFactTool(BaseTool):
    """The one route for "actually it's X, not Y"."""

    @property
    def name(self) -> str:
        return "notes_correct_fact"

    @property
    def description(self) -> str:
        return (
            "Correct a fact in an existing note: David says something you have written "
            "down is now wrong or has changed ('actually she's at Initech, not Globex', "
            "'his title is VP of Platform, not head of the team', 'that's the 2019 model "
            "not the 2018'). THIS is the tool for a correction — not notes_edit, and never "
            "notes_create (a second note about the same subject is how contradictory "
            "records happen).\n"
            "It replaces the stale value everywhere it is stated as CURRENT truth, "
            "including in the note's title, records the previous value under the note's "
            "History section with today's date, and leaves dated historical lines alone so "
            "a record of what happened at the old company stays accurate. It refuses "
            "without changing anything if the old value isn't actually in the note, so it "
            "can never quietly rewrite something you hadn't read.\n"
            "Find the note first (notes_search) and pass its real note_id."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": "The note holding the stale fact (from notes_search).",
                },
                "old_value": {
                    "type": "string",
                    "description": (
                        "The exact stale text as it appears in the note — 'Globex', "
                        "'head of the platform team'. Not a whole sentence."
                    ),
                },
                "new_value": {
                    "type": "string",
                    "description": "What it should say instead — 'Initech', 'VP of Platform'.",
                },
                "kind": {
                    "type": "string",
                    "enum": ["changed", "error"],
                    "description": (
                        "'changed' (the default) when the old value was true and no longer "
                        "is — she moved companies. 'error' when it was never true — you "
                        "wrote it down wrong. This only affects how the History line reads; "
                        "both update the current fact."
                    ),
                },
            },
            "required": ["note_id", "old_value", "new_value"],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        note_id = kwargs.get("note_id")
        old_value = (kwargs.get("old_value") or "").strip()
        new_value = (kwargs.get("new_value") or "").strip()
        kind = (kwargs.get("kind") or "changed").strip().lower()

        if not note_id:
            return ToolResult(success=False, message="note_id is required.")
        if not old_value:
            return ToolResult(success=False, message="old_value is required — what should it stop saying?")
        if not new_value:
            return ToolResult(success=False, message="new_value is required — what should it say instead?")
        if old_value.lower() == new_value.lower():
            return ToolResult(
                success=False,
                message=f"The note already says \"{new_value}\" — nothing to correct.",
            )

        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            note = db.query(Note).filter(
                Note.id == note_id, Note.user_id == user_id,
            ).first()
            if not note:
                return ToolResult(success=False, message="Note not found.")

            read_updated_at = note.updated_at
            current_content = note.content or ""
            current_title = note.title or ""

            new_content, replaced, left_historical = substitute_current_fact(
                current_content, old_value, new_value,
            )
            title_pattern = re.compile(re.escape(old_value), re.IGNORECASE)
            title_hits = len(title_pattern.findall(current_title))
            new_title = title_pattern.sub(new_value, current_title) if title_hits else current_title

            if not replaced and not title_hits:
                if left_historical:
                    return ToolResult(
                        success=False,
                        message=(
                            f"\"{old_value}\" only appears in this note's dated history, not in "
                            "what it states as currently true — so there is nothing to correct. "
                            "Nothing was changed. If a historical entry is itself wrong, say so "
                            "explicitly."
                        ),
                    )
                return ToolResult(
                    success=False,
                    message=(
                        f"Didn't find \"{old_value}\" in that note — nothing was changed. "
                        "Read the note first to see what it actually says."
                    ),
                )

            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if kind == "error":
                history_line = (
                    f"- {today}: corrected — this said \"{old_value}\"; that was wrong, "
                    f"it is \"{new_value}\"."
                )
            else:
                history_line = (
                    f"- {today}: was \"{old_value}\", now \"{new_value}\"."
                )
            final_content = append_history_line(new_content, history_line)

            full_text = f"{new_title}\n{final_content}" if new_title else final_content
            new_updated_at = datetime.now(timezone.utc)
            values: Dict[str, Any] = {
                "content": final_content,
                "updated_at": new_updated_at,
                "embedding": await get_embedding(full_text),
            }
            if new_title != current_title:
                values["title"] = new_title

            where_clause = [Note.id == note_id, Note.user_id == user_id]
            if read_updated_at is None:
                where_clause.append(Note.updated_at.is_(None))
            else:
                where_clause.append(Note.updated_at == read_updated_at)

            result = db.execute(sa_update(Note).where(*where_clause).values(**values))
            if result.rowcount == 0:
                db.rollback()
                return ToolResult(
                    success=False,
                    message=(
                        "This note changed while the correction was being applied — nothing "
                        "was written. Reread it and reissue the correction."
                    ),
                )
            db.commit()

            try:
                from app.services.note_connector import process_note_connections_sync
                await process_note_connections_sync(
                    str(note_id), user_id, new_title or "", final_content or "", db
                )
            except Exception as conn_err:
                logger.warning(f"Connection detection failed after fact correction: {conn_err}")

            parts = [f'Corrected "{old_value}" → "{new_value}"']
            if replaced:
                parts.append(f"{replaced} mention{'s' if replaced != 1 else ''} in the body")
            if title_hits:
                parts.append("and the title")
            if left_historical:
                parts.append(
                    f"({left_historical} dated historical mention"
                    f"{'s' if left_historical != 1 else ''} left as written)"
                )
            return ToolResult(
                success=True,
                data={
                    "note_id": str(note_id),
                    "title": new_title,
                    "content": final_content,
                    "replaced": replaced,
                    "title_updated": bool(title_hits),
                    "historical_left": left_historical,
                    "updated_at": new_updated_at.isoformat(),
                },
                message=" ".join(parts) + ".",
            )
        except Exception as e:
            db.rollback()
            logger.error(f"notes_correct_fact failed: {type(e).__name__}: {e}")
            return ToolResult(success=False, message=f"Failed to correct the note: {e}")
        finally:
            db.close()
