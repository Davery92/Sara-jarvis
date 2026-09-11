"""Chat episode writes keyed by client_message_id (harness rebuild Phase 7).

`store_conversation` used to deduplicate by ORDINAL: count the episodes already
in the DB for this conversation, skip that many entries of the incoming message
list, store the rest. That is only correct if turns are strictly serialized.

On 2026-09-11 turn 4 ran as a zombie for 500 seconds and stored mid-flight,
shifting the count under the turns that followed: two of David's six messages
never became episodes. The same skew is why every conversation double-stored
assistant reply #1 at turn 2 (gotcha_episode_ordinal_dup_store).

These run against the container's real Postgres — the partial unique index is
the thing under test — on a throwaway user whose rows are removed afterwards.
"""

import uuid

import pytest
from sqlalchemy import text

from app.db.session import SessionLocal
from app.main_simple import SimpleLLMClient, intelligent_memory_service


@pytest.fixture
def user(monkeypatch):
    uid = str(uuid.uuid4())
    db = SessionLocal()
    db.execute(
        text("INSERT INTO app_user (id, email, password_hash, created_at) "
             "VALUES (:id, :em, 'x', now())"),
        {"id": uid, "em": f"{uid}@test.invalid"},
    )
    db.commit()

    # Embeddings and the Neo4j/world-event fan-out are not what is under test.
    async def _no_embedding(self, *a, **kw):
        return None

    monkeypatch.setattr(
        "app.main_simple.IntelligentMemoryService._generate_embedding", _no_embedding
    )

    async def _no_topics(self, *a, **kw):
        return []

    monkeypatch.setattr(
        "app.main_simple.IntelligentMemoryService._extract_topics", _no_topics
    )
    try:
        yield uid
    finally:
        for tbl in ("conversation_turn", "episode", "event_outbox"):
            try:
                if tbl == "event_outbox":
                    db.execute(text(
                        "DELETE FROM event_outbox WHERE aggregate_id IN "
                        "(SELECT id FROM episode WHERE user_id = :u)"), {"u": uid})
                else:
                    db.execute(text(f"DELETE FROM {tbl} WHERE user_id = :u"), {"u": uid})
                db.commit()
            except Exception:
                db.rollback()
        for stmt in (
            "DELETE FROM world_event WHERE user_id = :u",
            "DELETE FROM conversation WHERE user_id = :u",
            "DELETE FROM app_user WHERE id = :u",
        ):
            try:
                db.execute(text(stmt), {"u": uid})
                db.commit()
            except Exception:
                db.rollback()
        db.close()


def _episodes(uid, conversation_id, role=None):
    db = SessionLocal()
    try:
        sql = ("SELECT id, role, content, client_message_id, reply_to_client_message_id "
               "FROM episode WHERE user_id = :u AND conversation_id = :c")
        params = {"u": uid, "c": conversation_id}
        if role:
            sql += " AND role = :r"
            params["r"] = role
        return db.execute(text(sql + " ORDER BY created_at"), params).fetchall()
    finally:
        db.close()


def _turns(uid, conversation_id):
    db = SessionLocal()
    try:
        return db.execute(text(
            "SELECT role, content, client_message_id FROM conversation_turn "
            "WHERE user_id = :u AND conversation_id = :c ORDER BY message_index"
        ), {"u": uid, "c": conversation_id}).fetchall()
    finally:
        db.close()


@pytest.mark.asyncio
class TestUserTurnIsStoredUpFront:
    async def test_one_call_stores_one_episode_and_one_turn(self, user):
        conv, cmid = str(uuid.uuid4()), str(uuid.uuid4())
        client = SimpleLLMClient()
        await client.persist_user_turn(user, conv, "download those attachments", cmid)

        eps = _episodes(user, conv, role="user")
        assert len(eps) == 1
        assert eps[0].content == "download those attachments"
        assert eps[0].client_message_id == cmid
        assert len(_turns(user, conv)) == 1

    async def test_the_same_message_twice_is_one_episode(self, user):
        """A retry, a reconnect, or a client that resends. This is the case
        ordinal dedup got right and everything else wrong."""
        conv, cmid = str(uuid.uuid4()), str(uuid.uuid4())
        client = SimpleLLMClient()
        await client.persist_user_turn(user, conv, "Well?", cmid)
        await client.persist_user_turn(user, conv, "Well?", cmid)

        assert len(_episodes(user, conv, role="user")) == 1
        assert len(_turns(user, conv)) == 1

    async def test_two_different_messages_are_two_episodes(self, user):
        """Two overlapping turns — the zombie case. Under ordinal dedup the
        second one's user message silently vanished."""
        conv = str(uuid.uuid4())
        client = SimpleLLMClient()
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        await client.persist_user_turn(user, conv, "Good morning Sara", a)
        await client.persist_user_turn(user, conv, "Well?", b)

        eps = _episodes(user, conv, role="user")
        assert len(eps) == 2
        assert {e.content for e in eps} == {"Good morning Sara", "Well?"}

    async def test_the_same_text_sent_twice_on_purpose_is_two_episodes(self, user):
        """David repeated himself four times on 2026-09-11. Content-based
        dedup would have lost three of those."""
        conv = str(uuid.uuid4())
        client = SimpleLLMClient()
        for _ in range(2):
            await client.persist_user_turn(
                user, conv, "Can you download those attachments?", str(uuid.uuid4())
            )
        assert len(_episodes(user, conv, role="user")) == 2

    async def test_live_context_is_stripped_before_storage(self, user):
        conv, cmid = str(uuid.uuid4()), str(uuid.uuid4())
        client = SimpleLLMClient()
        await client.persist_user_turn(
            user, conv,
            "<live_context>\nlots of awareness\n</live_context>\n\nGood morning",
            cmid,
        )
        eps = _episodes(user, conv, role="user")
        assert eps[0].content == "Good morning"
        turns = _turns(user, conv)
        assert not turns[0].content.startswith("<live_context>")

    async def test_ephemeral_stores_nothing(self, user):
        conv = str(uuid.uuid4())
        client = SimpleLLMClient()
        client._ephemeral = True
        await client.persist_user_turn(user, conv, "off the record", str(uuid.uuid4()))
        assert _episodes(user, conv) == []

    async def test_an_empty_message_stores_nothing(self, user):
        conv = str(uuid.uuid4())
        client = SimpleLLMClient()
        await client.persist_user_turn(user, conv, "   ", str(uuid.uuid4()))
        assert _episodes(user, conv) == []


@pytest.mark.asyncio
class TestAssistantEpisode:
    async def test_it_is_linked_to_the_user_turn_it_answers(self, user):
        conv, cmid = str(uuid.uuid4()), str(uuid.uuid4())
        client = SimpleLLMClient()
        await client.persist_user_turn(user, conv, "download those attachments", cmid)

        ep = await intelligent_memory_service.store_episode(
            user_id=user, role="assistant", content="Filed nine files to the Studio.",
            conversation_id=conv, client_message_id=f"reply-{cmid}",
            reply_to_client_message_id=cmid,
        )
        assert ep.reply_to_client_message_id == cmid

        replies = _episodes(user, conv, role="assistant")
        assert len(replies) == 1
        assert replies[0].reply_to_client_message_id == cmid

    async def test_storing_the_same_reply_twice_is_one_episode(self, user):
        """The turn-2 double-store: the same assistant reply written again by
        a later call with a shifted ordinal."""
        conv, cmid = str(uuid.uuid4()), str(uuid.uuid4())
        for _ in range(2):
            await intelligent_memory_service.store_episode(
                user_id=user, role="assistant", content="Filed nine files.",
                conversation_id=conv, client_message_id=f"reply-{cmid}",
                reply_to_client_message_id=cmid,
            )
        assert len(_episodes(user, conv, role="assistant")) == 1

    async def test_a_cancelled_turn_leaves_the_user_episode_alone(self, user):
        """Phase 3.4: a cancelled turn stores no assistant episode. The user
        turn is already durable and must stay."""
        conv, cmid = str(uuid.uuid4()), str(uuid.uuid4())
        client = SimpleLLMClient()
        await client.persist_user_turn(user, conv, "Well?", cmid)
        # ...client disconnects; nothing writes the assistant side.
        assert len(_episodes(user, conv, role="user")) == 1
        assert _episodes(user, conv, role="assistant") == []


class TestOrdinalDedupIsGone:
    def test_store_conversation_no_longer_counts_existing_episodes(self):
        import inspect

        src = inspect.getsource(SimpleLLMClient.store_conversation)
        assert "stored_count" not in src
        assert "idx < stored_count" not in src

    def test_it_no_longer_writes_user_episodes(self):
        import inspect

        src = inspect.getsource(SimpleLLMClient.store_conversation)
        assert 'role=role' not in src
        assert 'role="assistant"' in src

    def test_the_schema_carries_the_id(self):
        from app.schemas.chat import ChatMessage

        m = ChatMessage(role="user", content="hi", client_message_id="abc")
        assert m.client_message_id == "abc"
        assert ChatMessage(role="user", content="hi").client_message_id is None
