"""Integration tests for search_whole_foods."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import server


def parse(result: str) -> list:
    return json.loads(result)


class TestSearchPackagedGoods:
    async def test_search_cereal(self):
        results = parse(await server.search_whole_foods("cheerios"))
        assert len(results) > 0
        titles = [r["title"].lower() for r in results]
        assert any("cheerios" in t for t in titles)

    async def test_search_oat_milk(self):
        results = parse(await server.search_whole_foods("oat milk"))
        assert len(results) > 0
        titles = [r["title"].lower() for r in results]
        assert any("oat" in t for t in titles)


class TestSearchProduce:
    async def test_search_banana(self):
        results = parse(await server.search_whole_foods("banana"))
        assert len(results) > 0
        titles = [r["title"].lower() for r in results]
        assert any("banana" in t for t in titles)

    async def test_search_apple(self):
        results = parse(await server.search_whole_foods("apple"))
        assert len(results) > 0


class TestSearchMeat:
    async def test_search_chicken_thighs(self):
        results = parse(await server.search_whole_foods("chicken thighs"))
        assert len(results) > 0
        titles = [r["title"].lower() for r in results]
        assert any("chicken" in t for t in titles)


class TestSearchStoreBrand:
    async def test_search_365_brand(self):
        results = parse(await server.search_whole_foods("365 orange juice"))
        assert len(results) > 0


class TestSearchCommon:
    async def test_search_eggs(self):
        results = parse(await server.search_whole_foods("eggs"))
        assert len(results) > 0
        titles = [r["title"].lower() for r in results]
        assert any("egg" in t for t in titles)


class TestSearchEdgeCases:
    async def test_search_gibberish_returns_empty_or_few(self):
        results = parse(await server.search_whole_foods("xyzzyplugh99"))
        assert isinstance(results, list)

    async def test_search_single_char(self):
        results = parse(await server.search_whole_foods("a"))
        assert isinstance(results, list)


class TestSearchResultStructure:
    async def test_result_has_required_fields(self):
        results = parse(await server.search_whole_foods("milk"))
        assert len(results) > 0

        for r in results:
            assert "asin" in r
            assert "title" in r
            assert "price" in r
            assert "url" in r
            assert len(r["asin"]) >= 5
            assert r["url"].startswith("https://")

    async def test_returns_max_10_results(self):
        results = parse(await server.search_whole_foods("organic"))
        assert len(results) <= 10
