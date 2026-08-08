"""API-level checks: the audit must hold on what is actually served, at every k."""
import json

import django
import pytest
from django.test import Client

from banding import app  # noqa: F401  (configures settings on import)

django.setup()


@pytest.fixture
def client():
    return Client()


def test_up(client):
    assert client.get("/up").status_code == 200


def test_served_table_is_safe_at_every_k(client):
    for k in range(1, 13):
        d = client.get(f"/api/benchmarks?k={k}").json()
        assert d["audit"] == [], f"k={k} leaked: {d['audit']}"
        assert d["safe"] is True


def test_suppressed_cells_carry_no_numbers(client):
    d = client.get("/api/benchmarks?k=6").json()
    for cell in d["cells"]:
        if cell["suppressed"]:
            assert cell["p25"] is None and cell["p50"] is None and cell["p75"] is None


def test_higher_k_never_publishes_more(client):
    counts = [client.get(f"/api/benchmarks?k={k}").json()["published"] for k in range(1, 13)]
    assert counts == sorted(counts, reverse=True)


def test_bad_k_is_rejected(client):
    assert client.get("/api/benchmarks?k=abc").status_code == 400
    assert client.get("/api/benchmarks?k=999").status_code == 400


def test_graphql_filter_cannot_widen_disclosure(client):
    """Slicing to a single thin cell must still return it suppressed."""
    q = '{ benchmarks(k: 5, level: "L6", location: "denver") { cells { suppressed companies } } }'
    r = client.post("/graphql", data=json.dumps({"query": q}), content_type="application/json")
    cells = r.json()["data"]["benchmarks"]["cells"]
    assert cells and all(c["suppressed"] for c in cells)


def test_graphql_rejects_get(client):
    assert client.get("/graphql").status_code == 405


def test_graphql_reports_query_errors(client):
    r = client.post("/graphql", data='{"query":"{ nope }"}', content_type="application/json")
    assert r.status_code == 400
    assert "errors" in r.json()
