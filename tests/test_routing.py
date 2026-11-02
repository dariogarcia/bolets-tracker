import httpx
import pytest

from app import geocoding, routing
from app.models import Place
from app.zones import ZONES


class TestHaversine:
    def test_barcelona_to_solsona(self):
        d = routing.haversine_km(41.3851, 2.1734, 41.9934, 1.5171)
        assert 75 <= d <= 105

    def test_zero_distance(self):
        assert routing.haversine_km(42.0, 1.0, 42.0, 1.0) == pytest.approx(0.0)


class TestEstimate:
    def test_estimate_uses_road_factor(self):
        r = routing.estimate_route(41.3851, 2.1734, 41.9934, 1.5171)
        straight = routing.haversine_km(41.3851, 2.1734, 41.9934, 1.5171)
        assert r.distance_km == pytest.approx(straight * routing.ROAD_FACTOR, abs=0.2)
        assert r.duration_min > 0
        assert r.source == "estimate"


class TestRouteTable:
    async def test_osrm_table_parsed(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert "table" in str(request.url)
            return httpx.Response(
                200,
                json={
                    "code": "Ok",
                    "distances": [[0, 113000.0, 42000.0], [113000.0, 0, 90000.0], [42000.0, 90000.0, 0]],
                    "durations": [[0, 5770.0, 2100.0], [5770.0, 0, 4600.0], [2100.0, 4600.0, 0]],
                },
            )

        zones = ZONES[:2]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            routes = await routing.fetch_route_table(client, 41.3851, 2.1734, zones)

        assert len(routes) == 2
        assert routes[zones[0].id].source == "osrm"
        assert routes[zones[0].id].distance_km == 113.0
        assert routes[zones[0].id].duration_min == pytest.approx(96.2, abs=0.1)
        assert routes[zones[1].id].source == "osrm"

    async def test_fallback_on_osrm_failure(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("osrm down")

        zones = ZONES[:3]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            routes = await routing.fetch_route_table(client, 41.3851, 2.1734, zones)

        assert len(routes) == len(zones)
        for z in zones:
            assert routes[z.id].source == "estimate"

    async def test_fallback_on_osrm_error_code(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": "NoRoute"})

        zones = ZONES[:2]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            routes = await routing.fetch_route_table(client, 41.3851, 2.1734, zones)

        for z in zones:
            assert routes[z.id].source == "estimate"

    async def test_null_entries_get_estimate(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "code": "Ok",
                    "distances": [[0, 10000.0, None]],
                    "durations": [[0, 600.0, None]],
                },
            )

        zones = ZONES[:2]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            routes = await routing.fetch_route_table(client, 41.0, 1.0, zones)

        assert routes[zones[0].id].source == "osrm"
        assert routes[zones[1].id].source == "estimate"

    async def test_all_zones_routed_when_beyond_one_batch(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            n = str(request.url.path).count(";") + 1
            calls.append(n)
            row = [0.0] + [1000.0 * (i + 1) for i in range(n - 1)]
            return httpx.Response(
                200,
                json={"code": "Ok", "distances": [row], "durations": [row]},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            routes = await routing.fetch_route_table(client, 41.0, 1.0, ZONES)

        assert len(ZONES) > routing.MAX_TABLE_SIZE
        assert len(calls) > 1
        assert all(n <= routing.MAX_TABLE_SIZE for n in calls)
        assert set(routes) == {z.id for z in ZONES}
        assert all(r.source == "osrm" for r in routes.values())


class TestGeocoding:
    def test_preset_substring_match(self):
        matches = geocoding._preset_matches("barce")
        assert any(p.name == "Barcelona" for p in matches)

    def test_preset_no_match_on_empty(self):
        assert geocoding._preset_matches("") == []

    async def test_geocode_filters_to_catalonia_and_merges_presets(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "name": "Vic",
                            "latitude": 41.93,
                            "longitude": 2.254,
                            "country_code": "ES",
                            "admin1": "Catalunya",
                            "admin2": "Província de Barcelona",
                            "admin3": "Osona",
                            "country": "Espanya",
                            "population": 46942,
                        },
                        {
                            "name": "Vic",
                            "latitude": 43.5,
                            "longitude": 5.0,
                            "country_code": "FR",
                            "admin1": "Provence",
                            "country": "France",
                        },
                    ]
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            places = await geocoding.geocode(client, "vic")

        names = [p.name for p in places]
        assert names.count("Vic") == 1
        assert all(p.lat < 43 for p in places)

    async def test_geocode_survives_api_failure(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("geocoder down")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            places = await geocoding.geocode(client, "girona")

        assert any(isinstance(p, Place) and p.name == "Girona" for p in places)
