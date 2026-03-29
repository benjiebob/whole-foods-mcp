"""Integration tests for cart management: view, remove, clear."""

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


class TestViewCart:
    async def test_view_empty_cart(self, clean_cart):
        cart = parse(await server.view_cart())
        assert "items" in cart
        assert isinstance(cart["items"], list)

    async def test_view_cart_after_add(self, clean_cart):
        asin = await first_asin("cheerios")
        await server.add_to_cart(asin)

        cart = parse(await server.view_cart())
        assert len(cart["items"]) > 0

        item = cart["items"][0]
        assert "asin" in item
        assert "title" in item
        assert "quantity" in item


class TestRemoveFromCart:
    async def test_remove_item(self, clean_cart):
        asin = await first_asin("cheerios")
        await server.add_to_cart(asin)

        cart = parse(await server.view_cart())
        cart_asins = [i["asin"] for i in cart["items"]]
        assert asin in cart_asins

        result = parse(await server.remove_from_cart(asin))
        assert result.get("removed") is True

        cart = parse(await server.view_cart())
        cart_asins = [i["asin"] for i in cart["items"]]
        assert asin not in cart_asins

    async def test_remove_nonexistent_item(self, clean_cart):
        result = parse(await server.remove_from_cart("NOTINCART12345"))
        assert "error" in result


class TestClearCart:
    async def test_clear_empty_cart(self, clean_cart):
        result = parse(await server.clear_cart())
        assert result.get("cleared") is True

    async def test_clear_cart_with_items(self):
        asin1 = await first_asin("cheerios")
        asin2 = await first_asin("oat milk")
        await server.add_to_cart(asin1)
        await server.add_to_cart(asin2)

        cart = parse(await server.view_cart())
        assert len(cart["items"]) >= 2

        result = parse(await server.clear_cart())
        assert result.get("cleared") is True

        cart = parse(await server.view_cart())
        assert len(cart["items"]) == 0
