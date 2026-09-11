"""files_to_studio — email attachments become downloadable Studio artifacts.

Harness rebuild Phase 4. On 2026-09-11 David asked four times for the
attachments on Jim's emails to end up somewhere he could open them. Every
piece already existed — EmailAttachment.minio_bucket/minio_key,
Artifact(artifact_type="file"), GET /api/artifacts/{id}/download, an iOS
Studio that lists file artifacts — and nothing joined them up, so he got
capability essays instead of files.

These run against the container's real Postgres (JSONB, and the join that
enforces ownership, are the parts worth testing), on a throwaway user whose
rows are removed afterwards. MinIO is stubbed: object storage is not what is
under test here.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.session import SessionLocal
from app.models.artifact import Artifact
from app.models.email import Email, EmailAttachment
from app.tools.email import FilesToStudioTool


BYTES = {
    "CA-0 Tool Spec.docx": b"PK\x03\x04 fake docx bytes " + b"a" * 200,
    "CA-2 Renewal.pdf": b"%PDF-1.4 fake pdf bytes " + b"b" * 300,
}


class FakeProcessor:
    """Stands in for DocumentProcessor. Records what it was asked for so the
    bucket handoff (EmailAttachment.minio_bucket -> get_file) is checkable."""

    def __init__(self):
        self.fetched = []
        self.stored = {}

    def get_file(self, storage_key, bucket=None):
        self.fetched.append((storage_key, bucket))
        payload = BYTES.get(storage_key.split("/")[-1])
        if payload is None:
            raise RuntimeError(f"no such object {bucket}/{storage_key}")
        return payload

    async def store_file(self, content, filename, mime):
        key = f"{uuid.uuid4()}-{filename}"
        self.stored[key] = (content, filename, mime)
        return key


@pytest.fixture
def seeded(monkeypatch):
    """A throwaway user with one email carrying two non-inline attachments
    (plus one inline one, which must never be filed)."""
    user_id = str(uuid.uuid4())
    email_id = str(uuid.uuid4())
    db = SessionLocal()
    made = []
    try:
        db.execute(
            __import__("sqlalchemy").text(
                "INSERT INTO app_user (id, email, password_hash, created_at) "
                "VALUES (:id, :em, 'x', now())"
            ),
            {"id": user_id, "em": f"{user_id}@test.invalid"},
        )
        email = Email(
            id=email_id,
            user_id=user_id,
            mailbox="david@avery.cloud",
            subject="Tool specs",
            sender_email="jim@example.com",
            sender_name="Jim",
            received_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db.add(email)
        for name, inline in (
            ("CA-0 Tool Spec.docx", False),
            ("CA-2 Renewal.pdf", False),
            ("signature.png", True),
        ):
            att = EmailAttachment(
                id=str(uuid.uuid4()),
                email_id=email_id,
                filename=name,
                content_type="application/octet-stream",
                size=len(BYTES.get(name, b"")),
                is_inline=inline,
                minio_bucket="riskninja-docs" if name.startswith("CA-2") else "sara-docs",
                minio_key=f"attachments/{name}",
            )
            db.add(att)
            made.append(att.id)
        db.commit()

        proc = FakeProcessor()
        monkeypatch.setattr("app.services.docs_ingest.DocumentProcessor", lambda: proc)
        yield {"user_id": user_id, "email_id": email_id, "attachment_ids": made,
               "processor": proc}
    finally:
        sa = __import__("sqlalchemy")
        db.rollback()
        db.execute(sa.text("DELETE FROM artifacts WHERE user_id = :u"), {"u": user_id})
        db.execute(sa.text("DELETE FROM email_attachment WHERE email_id = :e"),
                   {"e": email_id})
        db.execute(sa.text("DELETE FROM email WHERE id = :e"), {"e": email_id})
        db.execute(sa.text("DELETE FROM app_user WHERE id = :u"), {"u": user_id})
        db.commit()
        db.close()


def _artifacts(user_id):
    db = SessionLocal()
    try:
        return db.query(Artifact).filter(
            Artifact.user_id == user_id, Artifact.artifact_type == "file"
        ).order_by(Artifact.title).all()
    finally:
        db.close()


@pytest.mark.asyncio
class TestFilesToStudio:
    async def test_email_ids_files_every_non_inline_attachment(self, seeded):
        r = await FilesToStudioTool().execute(
            seeded["user_id"], email_ids=[seeded["email_id"]], title="Jim's tools"
        )
        assert r.success, r.message

        arts = _artifacts(seeded["user_id"])
        assert [a.title for a in arts] == ["CA-0 Tool Spec.docx", "CA-2 Renewal.pdf"]
        # The inline signature image is never a deliverable.
        assert "signature.png" not in r.message

    async def test_each_artifact_is_actually_downloadable(self, seeded):
        r = await FilesToStudioTool().execute(
            seeded["user_id"], email_ids=[seeded["email_id"]], title="Jim's tools"
        )
        for f in r.data["files"]:
            assert f["download_url"] == f"/api/artifacts/{f['artifact_id']}/download"

        for art in _artifacts(seeded["user_id"]):
            c = art.content
            # What GET /{id}/download requires: type "file" plus a storage_key.
            assert art.artifact_type == "file"
            assert c["storage_key"] in seeded["processor"].stored
            assert c["filename"] == art.title
            assert c["size"] > 0
            assert c["source"]["email_id"] == seeded["email_id"]
            assert c["source"]["sender"] == "jim@example.com"
            assert art.artifact_metadata["group"] == "Jim's tools"

    async def test_the_attachments_own_bucket_is_honoured(self, seeded):
        await FilesToStudioTool().execute(
            seeded["user_id"], email_ids=[seeded["email_id"]]
        )
        buckets = dict(
            (k.split("/")[-1], b) for k, b in seeded["processor"].fetched
        )
        # riskninja-docs and sara-docs are both real buckets; reading the
        # second from the first is how this silently returns nothing.
        assert buckets["CA-2 Renewal.pdf"] == "riskninja-docs"
        assert buckets["CA-0 Tool Spec.docx"] == "sara-docs"

    async def test_running_it_twice_does_not_duplicate(self, seeded):
        await FilesToStudioTool().execute(
            seeded["user_id"], email_ids=[seeded["email_id"]]
        )
        second = await FilesToStudioTool().execute(
            seeded["user_id"], email_ids=[seeded["email_id"]]
        )
        assert len(_artifacts(seeded["user_id"])) == 2
        assert second.success
        assert "Already in the Studio" in second.message

    async def test_skip_duplicates_false_files_again(self, seeded):
        await FilesToStudioTool().execute(
            seeded["user_id"], email_ids=[seeded["email_id"]]
        )
        await FilesToStudioTool().execute(
            seeded["user_id"], email_ids=[seeded["email_id"]], skip_duplicates=False
        )
        assert len(_artifacts(seeded["user_id"])) == 4

    async def test_specific_attachment_ids(self, seeded):
        one = seeded["attachment_ids"][0]
        r = await FilesToStudioTool().execute(seeded["user_id"], attachment_ids=[one])
        assert r.success
        assert len(r.data["files"]) == 1

    async def test_sender_search(self, seeded):
        r = await FilesToStudioTool().execute(
            seeded["user_id"], sender="jim@", days=30, title="Jim's tools"
        )
        assert r.success
        assert len(r.data["files"]) == 2

    async def test_another_users_attachments_are_invisible(self, seeded):
        stranger = str(uuid.uuid4())
        r = await FilesToStudioTool().execute(
            stranger, attachment_ids=seeded["attachment_ids"]
        )
        assert r.data["files"] == []
        assert _artifacts(stranger) == []

    async def test_no_match_says_so_instead_of_claiming_success(self, seeded):
        r = await FilesToStudioTool().execute(
            seeded["user_id"], sender="nobody@nowhere.invalid"
        )
        assert r.data["files"] == []
        assert "nothing was filed" in r.message.lower()

    async def test_no_selector_at_all_is_refused(self, seeded):
        r = await FilesToStudioTool().execute(seeded["user_id"])
        assert r.success is False
        assert "attachment_ids" in r.message

    async def test_the_message_names_the_files_and_the_studio(self, seeded):
        r = await FilesToStudioTool().execute(
            seeded["user_id"], email_ids=[seeded["email_id"]], title="Jim's tools"
        )
        # Whatever else degrades, the status line itself has to be usable: this
        # is the string that reaches David when a turn ends on a tool result.
        assert "Studio" in r.message
        assert "CA-0 Tool Spec.docx" in r.message
        assert "Jim's tools" in r.message


class TestRegistration:
    def test_it_is_registered_and_in_the_chat_core(self):
        from app.services.tool_retrieval import CORE_TOOLS
        from app.tools.registry import tool_registry

        assert tool_registry.get_tool("files_to_studio") is not None
        assert "files_to_studio" in CORE_TOOLS

    def test_it_requires_a_user_turn(self):
        # Same guard as workspace_job_run: the autonomous loop must not file
        # things into David's Studio on its own initiative.
        assert FilesToStudioTool().requires_user_origin is True
