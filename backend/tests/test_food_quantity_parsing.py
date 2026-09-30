"""Food quantity/unit parsing (Sara repair plan R08, evidence
J05_trial2_TURNS1_4_SEARCH_MATCH_AND_SCALING_AND_DUPLICATE).

Confirmed mechanism: `_parse_food_items`'s unit alternation listed each
unit's SHORT form before its longer forms ("g" before "gram"/"grams", "cup"
before "cups", "slice" before "slices"). Python's `re` alternation is
leftmost-alternative-wins (not longest-match), so "150 grams chicken
breast" matched unit="g" and left "rams chicken breast" as the parsed food
NAME — not just a wrong unit, a wrong (and wrong-looking) search term that
would either fail to match anything in the food database or match the
wrong food entirely.
"""
from app.tools.fitness.food_search_log import FoodSearchAndLogTool


def _tool():
    return FoodSearchAndLogTool.__new__(FoodSearchAndLogTool)


class TestFoodQuantityParsing:
    def test_grams_word_form_does_not_truncate_the_food_name(self):
        items = _tool()._parse_food_items("150 grams chicken breast")
        assert items == [(150.0, "grams", "chicken breast")]

    def test_gram_singular_word_form_does_not_truncate_the_food_name(self):
        items = _tool()._parse_food_items("150 gram chicken breast")
        assert items == [(150.0, "gram", "chicken breast")]

    def test_grams_with_no_space_does_not_truncate_the_food_name(self):
        items = _tool()._parse_food_items("150grams chicken breast")
        assert items == [(150.0, "grams", "chicken breast")]

    def test_short_g_form_still_works(self):
        items = _tool()._parse_food_items("150g chicken breast")
        assert items == [(150.0, "g", "chicken breast")]

    def test_cups_plural_does_not_truncate_the_food_name(self):
        items = _tool()._parse_food_items("2 cups flour")
        assert items == [(2.0, "cups", "flour")]

    def test_slices_plural_does_not_truncate_the_food_name(self):
        items = _tool()._parse_food_items("3 slices bread")
        assert items == [(3.0, "slices", "bread")]

    def test_no_unit_at_all_still_parses_as_one_serving_style(self):
        items = _tool()._parse_food_items("3 eggs")
        assert items == [(3.0, None, "eggs")]

    def test_oz_form_still_works(self):
        items = _tool()._parse_food_items("4oz ground beef")
        assert items == [(4.0, "oz", "ground beef")]

    def test_size_words_still_work(self):
        items = _tool()._parse_food_items("2 large chicken breasts")
        assert items == [(2.0, "large", "chicken breasts")]

    def test_multiple_items_separated_by_and(self):
        items = _tool()._parse_food_items("150 grams chicken breast and 2 cups rice")
        assert items == [(150.0, "grams", "chicken breast"), (2.0, "cups", "rice")]
