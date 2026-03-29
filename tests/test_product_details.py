"""Integration tests for get_product_details."""

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


class TestProductDetails:
    async def test_packaged_product_details(self):
        asin = await first_asin("cheerios")
        details = parse(await server.get_product_details(asin))

        assert details["asin"] == asin
        assert len(details["title"]) > 0
        assert "url" in details
        assert details["url"].startswith("https://")

    async def test_produce_product_details(self):
        asin = await first_asin("banana")
        details = parse(await server.get_product_details(asin))

        assert details["asin"] == asin
        assert len(details["title"]) > 0

    async def test_details_include_features(self):
        asin = await first_asin("cheerios")
        details = parse(await server.get_product_details(asin))

        assert "features" in details
        assert isinstance(details["features"], list)

    async def test_screenshot_exists(self):
        asin = await first_asin("oat milk")
        details = parse(await server.get_product_details(asin))

        assert "screenshot" in details
        screenshot_path = Path(details["screenshot"])
        assert screenshot_path.exists()
        assert screenshot_path.suffix == ".png"
        assert screenshot_path.stat().st_size > 0

    async def test_image_url(self):
        asin = await first_asin("cheerios")
        details = parse(await server.get_product_details(asin))

        assert "imageUrl" in details
        if details["imageUrl"]:
            assert details["imageUrl"].startswith("http")
