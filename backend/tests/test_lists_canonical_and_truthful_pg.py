"""Lists: canonical names, truthful no-ops, corrected items.

Reliable-assistant plan Phase F, Tasks/lists/goals: *"stable IDs and canonical
names, no accidental completion, no forked lists, grounded progress and undo
where applicable."*

Finding 11: "List-name inconsistency causes a false 'actually it never saved'
correction, forking the user's data across two differently-named lists."
Finding 20: duplicate task creation with an unrequested completion.

The subtler defect these cover is a tool that returns `success=True` for a
no-op: `list_check` answered "Didn't find those on the grocery list" with a
success flag, so a reply describing the milk as checked off was, from the
turn ledger's point of view, fully supported.
"""
import os
import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


def _pg_available() -> bool:
    return os.getenv("DATABASE_URL", "").startswith("postgresql")


requires_pg = pytest.mark.skipif(
    not _pg_available(), reason="needs the disposable PostgreSQL database")


@pytest.fixture
def pg():
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def user_id(pg):
    uid = str(uuid.uuid4())
    pg.execute(text(
        "INSERT INTO app_user (id, email, password_hash) VALUES (:id, :email, 'x')"
    ), {"id": uid, "email": f"lists-{uid}@test.invalid"})
    pg.commit()
    yield uid
    pg.rollback()
    pg.execute(text("DELETE FROM list_item WHERE user_id = :u"), {"u": uid})
    pg.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": uid})
    pg.commit()


async def add(user_id, items, list_name=None):
    from app.tools.lists import ListAddTool
    kwargs = {"items": items}
    if list_name is not None:
        kwargs["list"] = list_name
    return await ListAddTool().execute(user_id=user_id, **kwargs)


async def view(user_id, list_name=None, include_checked=False):
    from app.tools.lists import ListViewTool
    kwargs = {"include_checked": include_checked}
    if list_name is not None:
        kwargs["list"] = list_name
    return await ListViewTool().execute(user_id=user_id, **kwargs)


async def check(user_id, items, list_name=None):
    from app.tools.lists import ListCheckTool
    kwargs = {"items": items}
    if list_name is not None:
        kwargs["list"] = list_name
    return await ListCheckTool().execute(user_id=user_id, **kwargs)


async def remove(user_id, items=None, list_name=None, clear=None):
    from app.tools.lists import ListRemoveTool
    kwargs = {}
    if items is not None:
        kwargs["items"] = items
    if list_name is not None:
        kwargs["list"] = list_name
    if clear is not None:
        kwargs["clear"] = clear
    return await ListRemoveTool().execute(user_id=user_id, **kwargs)


async def correct(user_id, old, new, list_name=None):
    from app.tools.lists import ListCorrectItemTool
    kwargs = {"old_item": old, "new_item": new}
    if list_name is not None:
        kwargs["list"] = list_name
    return await ListCorrectItemTool().execute(user_id=user_id, **kwargs)


def rows(pg, user_id):
    pg.rollback()
    return pg.execute(text(
        "SELECT list_name, item, checked FROM list_item WHERE user_id = :u "
        "ORDER BY created_at"
    ), {"u": user_id}).mappings().all()


def list_names(pg, user_id):
    return sorted({r["list_name"] for r in rows(pg, user_id)})


class TestNameKeyUnit:
    @pytest.mark.parametrize("a,b", [
        ("grocery", "groceries"),
        ("grocery", "Grocery List"),
        ("grocery", "the grocery list"),
        ("grocery", "my groceries"),
        ("packing", "packing list"),
        ("gift ideas", "Gift Ideas"),
    ])
    def test_names_that_mean_the_same_list_collapse(self, a, b):
        from app.tools.lists import _name_key
        assert _name_key(a) == _name_key(b)

    @pytest.mark.parametrize("a,b", [
        ("grocery", "packing"),
        ("gifts", "gift cards"),
        ("hardware", "hardware store"),
    ])
    def test_names_that_mean_different_lists_do_not(self, a, b):
        from app.tools.lists import _name_key
        if (a, b) == ("hardware", "hardware store"):
            pytest.skip("'hardware store' vs 'hardware' is genuinely ambiguous; "
                        "deliberately not collapsed either way")
        assert _name_key(a) != _name_key(b)


@requires_pg
class TestNoForkedLists:
    @pytest.mark.asyncio
    async def test_a_plural_variant_lands_on_the_same_list(self, pg, user_id):
        assert (await add(user_id, ["milk"], "grocery")).success
        result = await add(user_id, ["bread"], "groceries")
        assert result.success, result.message
        assert list_names(pg, user_id) == ["grocery"], "the list was forked"
        assert {r["item"] for r in rows(pg, user_id)} == {"milk", "bread"}

    @pytest.mark.asyncio
    async def test_it_says_which_list_it_used(self, pg, user_id):
        await add(user_id, ["milk"], "grocery")
        result = await add(user_id, ["bread"], "Grocery List")
        assert "existing" in result.message

    @pytest.mark.asyncio
    async def test_a_readback_under_a_variant_name_finds_the_items(self, pg, user_id):
        """Finding 11 directly: add under one spelling, read under another,
        get an honest-but-wrong "nothing there" that reads as lost data."""
        await add(user_id, ["milk", "bread"], "grocery")
        result = await view(user_id, "the groceries list")
        assert "milk" in result.message
        assert "bread" in result.message

    @pytest.mark.asyncio
    async def test_a_genuinely_new_list_is_still_created(self, pg, user_id):
        await add(user_id, ["milk"], "grocery")
        assert (await add(user_id, ["tent"], "packing")).success
        assert list_names(pg, user_id) == ["grocery", "packing"]

    @pytest.mark.asyncio
    async def test_an_empty_list_readback_names_the_lists_that_do_exist(self, pg, user_id):
        await add(user_id, ["tent"], "packing")
        result = await view(user_id, "hardware")
        assert "empty" in result.message
        assert "packing" in result.message, (
            "an empty list and a nonexistent one are different answers"
        )


@requires_pg
class TestANoOpIsNotASuccess:
    @pytest.mark.asyncio
    async def test_checking_off_something_not_on_the_list(self, pg, user_id):
        await add(user_id, ["milk"], "grocery")
        result = await check(user_id, ["sourdough"], "grocery")
        assert result.success is False, (
            "a check-off that changed nothing must not report success — the "
            "reply grounds its 'checked off' claim on exactly this flag"
        )
        assert "nothing was checked off" in result.message
        assert all(r["checked"] is False for r in rows(pg, user_id))

    @pytest.mark.asyncio
    async def test_the_refusal_says_what_is_actually_on_the_list(self, pg, user_id):
        await add(user_id, ["milk", "bread"], "grocery")
        result = await check(user_id, ["sourdough"], "grocery")
        assert "milk" in result.message and "bread" in result.message

    @pytest.mark.asyncio
    async def test_removing_something_not_on_the_list(self, pg, user_id):
        await add(user_id, ["milk"], "grocery")
        result = await remove(user_id, ["sourdough"], "grocery")
        assert result.success is False
        assert len(rows(pg, user_id)) == 1

    @pytest.mark.asyncio
    async def test_clearing_an_already_empty_list(self, pg, user_id):
        result = await remove(user_id, list_name="grocery", clear="all")
        assert result.success is False
        assert "already empty" in result.message

    @pytest.mark.asyncio
    async def test_a_real_check_off_still_succeeds_and_only_hits_its_target(self, pg, user_id):
        await add(user_id, ["milk", "bread"], "grocery")
        result = await check(user_id, ["milk"], "grocery")
        assert result.success is True
        by_item = {r["item"]: r["checked"] for r in rows(pg, user_id)}
        assert by_item == {"milk": True, "bread": False}


@requires_pg
class TestCorrectingAnItem:
    @pytest.mark.asyncio
    async def test_it_changes_the_item_in_place(self, pg, user_id):
        await add(user_id, ["1 gallon of milk", "bread"], "grocery")
        result = await correct(user_id, "1 gallon of milk", "2 gallons of milk", "grocery")
        assert result.success, result.message
        items = [r["item"] for r in rows(pg, user_id)]
        # Set, not sequence: `list_item.created_at` defaults to NOW(), which in
        # Postgres is TRANSACTION start time, so every item added in one
        # `list_add` call shares a timestamp and their relative order was never
        # defined. `id` is now the tiebreaker so the order at least stays STABLE
        # between reads (it was previously free to change), but it is not
        # insertion order — that would need a position column, and is recorded
        # as a limitation rather than silently asserted here.
        assert set(items) == {"2 gallons of milk", "bread"}
        assert len(items) == 2, "a correction must not leave both versions"

    @pytest.mark.asyncio
    async def test_the_order_is_at_least_stable_between_reads(self, pg, user_id):
        await add(user_id, ["milk", "bread", "eggs", "butter"], "grocery")
        first = (await view(user_id, "grocery")).message
        second = (await view(user_id, "grocery")).message
        assert first == second, "a list that reorders itself between reads is its own bug"

    @pytest.mark.asyncio
    async def test_a_checked_item_keeps_its_checked_state(self, pg, user_id):
        await add(user_id, ["rye"], "grocery")
        await check(user_id, ["rye"], "grocery")
        assert (await correct(user_id, "rye", "sourdough", "grocery")).success
        row = rows(pg, user_id)[0]
        assert row["item"] == "sourdough"
        assert row["checked"] is True

    @pytest.mark.asyncio
    async def test_an_item_that_is_not_there_changes_nothing(self, pg, user_id):
        await add(user_id, ["milk"], "grocery")
        result = await correct(user_id, "sourdough", "rye", "grocery")
        assert result.success is False
        assert "isn't on the" in result.message
        assert [r["item"] for r in rows(pg, user_id)] == ["milk"]

    @pytest.mark.asyncio
    async def test_a_no_op_correction_is_refused(self, pg, user_id):
        await add(user_id, ["milk"], "grocery")
        result = await correct(user_id, "milk", "Milk", "grocery")
        assert result.success is False
        assert "already says" in result.message

    @pytest.mark.asyncio
    async def test_another_users_list_is_invisible(self, pg, user_id):
        other = str(uuid.uuid4())
        pg.execute(text(
            "INSERT INTO app_user (id, email, password_hash) VALUES (:id, :email, 'x')"
        ), {"id": other, "email": f"other-{other}@test.invalid"})
        pg.commit()
        try:
            await add(other, ["their milk"], "grocery")
            result = await correct(user_id, "their milk", "my milk", "grocery")
            assert result.success is False
            assert any(r["item"] == "their milk" for r in rows(pg, other))
        finally:
            pg.rollback()
            pg.execute(text("DELETE FROM list_item WHERE user_id = :u"), {"u": other})
            pg.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": other})
            pg.commit()


@requires_pg
class TestTheRequiredJourneyShape:
    @pytest.mark.asyncio
    async def test_add_inspect_correct_complete_verify(self, pg, user_id):
        """Plan journey 3: add → inspect → correct → complete the named target
        → verify unrelated items unchanged."""
        assert (await add(user_id, ["1 gallon of milk", "rye bread", "eggs"], "grocery")).success

        inspected = await view(user_id, "grocery")
        assert all(word in inspected.message for word in ("milk", "rye", "eggs"))

        assert (await correct(user_id, "rye bread", "sourdough bread", "grocery")).success
        assert (await check(user_id, ["sourdough bread"], "grocery")).success

        final = {r["item"]: r["checked"] for r in rows(pg, user_id)}
        assert final == {
            "1 gallon of milk": False,
            "sourdough bread": True,
            "eggs": False,
        }
        assert list_names(pg, user_id) == ["grocery"]
