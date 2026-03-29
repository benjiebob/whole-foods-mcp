"""Integration tests for add_to_cart."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import server


def parse(result):
    return json.loads(result)


async def first_asin(query):
    results = parse(await server.search_whole_foods(query))
    assert len(results) > 0, f"No search results for '{query}'"
    return results[0]["asin"]


class TestAddPackagedItem:
    async def test_add_cereal(self, clean_cart):
        asin = await first_asin("cheerios")
        result = parse(await server.add_to_cart(asin))

        assert "added" in result, f"Expected 'added' in result, got: {result}"
        assert result["asin"] == asin

        cart = parse(await server.view_cart())
        cart_asins = [item["asin"] for item in cart["items"]]
        assert asin in cart_asins

    async def test_add_with_quantity(self, clean_cart):
        asin = await first_asin("oat milk")
        result = parse(await server.add_to_cart(asin, quantity=2))

        assert "added" in result
        assert result["quantity"] == 2


class TestAddWeightBasedItem:
    async def test_add_banana(self, clean_cart):
        asin = await first_asin("banana")
        result = parse(await server.add_to_cart(asin))

        assert "added" in result, f"Expected success, got: {result}"

    async def test_add_chicken(self, clean_cart):
        asin = await first_asin("chicken thighs")
        result = parse(await server.add_to_cart(asin))

        assert "added" in result, f"Expected success, got: {result}"


class TestAddEdgeCases:
    async def test_invalid_asin(self, clean_cart):
        result = parse(await server.add_to_cart("INVALIDASIN123"))

        assert "error" in result or "success" in result
        if "success" in result:
            assert result["success"] is False

    async def test_add_same_item_twice(self, clean_cart):
        asin = await first_asin("cheerios")

        result1 = parse(await server.add_to_cart(asin))
        assert "added" in result1

        result2 = parse(await server.add_to_cart(asin))
        assert "added" in result2

        cart = parse(await server.view_cart())
        cart_asins = [item["asin"] for item in cart["items"]]
        assert asin in cart_asins
