"""
SARA_INTELLIGENT_FOOD_LOGGING_PLAN_2026_08_16 Stage A — canonical food item v2
schema + fixture round-trip, mirroring test_singular_sara_slice.py's contract
test. Field-name parity with TypeScript (iOS + web) is checked separately by
ios-app/scripts/check-food-contract-parity.mjs, which this test does not
duplicate.
"""

import json
from pathlib import Path

FIXTURES_PATH = (
    Path(__file__).parent.parent / "app" / "schemas" / "fixtures" / "food_item_v2_examples.json"
)

SINGLE_ITEM_KEYS = {
    "fatsecret_real_serving",
    "synthetic_gram_serving",
    "custom_food",
    "recipe_serving",
    "unresolved_manual_item",
    "legacy_ios_snapshot",
    "legacy_web_snapshot",
}


class TestFoodItemV2Contract:
    def test_fixtures_file_round_trips_against_schema(self):
        from app.schemas.food_item import CanonicalFoodItemV2, FOOD_ITEM_SCHEMA_VERSION

        fixtures = json.loads(FIXTURES_PATH.read_text())

        fixture_keys = {k for k in fixtures if not k.startswith("_") and k != "schema_version"}
        assert fixture_keys == SINGLE_ITEM_KEYS | {"multi_item_meal"}

        for key in SINGLE_ITEM_KEYS:
            instance = CanonicalFoodItemV2.model_validate(fixtures[key])
            assert instance.schema_version == FOOD_ITEM_SCHEMA_VERSION
            # Round-trip: dump back to JSON-compatible dict and re-validate.
            CanonicalFoodItemV2.model_validate(instance.model_dump(mode="json"))

        # multi_item_meal is a list of items sharing one meal, not one item.
        items = fixtures["multi_item_meal"]
        assert len(items) > 1
        line_ids = set()
        for raw_item in items:
            instance = CanonicalFoodItemV2.model_validate(raw_item)
            CanonicalFoodItemV2.model_validate(instance.model_dump(mode="json"))
            line_ids.add(instance.line_id)
        assert len(line_ids) == len(items), "line_id must be unique within one meal"

    def test_legacy_snapshots_use_stored_snapshot_basis(self):
        """v1 rows have no serving provenance to re-derive — reading one back
        as v2 must say so, not claim a resolved-serving match it can't back up."""
        from app.schemas.food_item import CanonicalFoodItemV2

        fixtures = json.loads(FIXTURES_PATH.read_text())
        for key in ("legacy_ios_snapshot", "legacy_web_snapshot"):
            instance = CanonicalFoodItemV2.model_validate(fixtures[key])
            assert instance.nutrition_basis == "stored_snapshot"

    def test_unresolved_manual_item_flags_low_confidence(self):
        from app.schemas.food_item import CanonicalFoodItemV2

        fixtures = json.loads(FIXTURES_PATH.read_text())
        instance = CanonicalFoodItemV2.model_validate(fixtures["unresolved_manual_item"])
        assert instance.nutrition_basis == "estimated"
        assert instance.resolution_confidence < 0.5
        assert instance.estimate_notes

    def test_schema_version_defaults_without_explicit_value(self):
        from app.schemas.food_item import CanonicalFoodItemV2, FOOD_ITEM_SCHEMA_VERSION

        item = CanonicalFoodItemV2(
            line_id="test-line-1", name="Test Food", source="manual",
            quantity=1, unit="serving",
        )
        assert item.schema_version == FOOD_ITEM_SCHEMA_VERSION
