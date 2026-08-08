"""Django surface: a benchmark API and a GraphQL endpoint over the same table.

Kept to a single module on purpose. There is one interesting thing in this
project and it lives in bench/disclosure.py; the web layer's whole job is to make
that behaviour pokeable without becoming the subject.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.urls import path
from graphql import (
    GraphQLArgument,
    GraphQLBoolean,
    GraphQLField,
    GraphQLInt,
    GraphQLList,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    graphql_sync,
)

from bench.disclosure import DEFAULT_K, Observation, audit, build

BASE = Path(__file__).resolve().parent.parent

if not settings.configured:
    settings.configure(
        DEBUG=False,
        ALLOWED_HOSTS=["*"],
        SECRET_KEY="not-a-secret-this-service-stores-nothing",
        ROOT_URLCONF=__name__,
        DATABASES={},
        INSTALLED_APPS=[],
        MIDDLEWARE=[],
    )


# -- the sample market ----------------------------------------------------

LEVELS = ["L3", "L4", "L5", "L6"]
LOCATIONS = ["seattle", "denver", "austin", "remote"]


def sample_market(seed: int = 7) -> list[Observation]:
    """A synthetic contributor set with deliberately uneven coverage, so some
    cells are thin and the suppression rules actually have something to do."""
    rng = random.Random(seed)
    out: list[Observation] = []
    for level_i, level in enumerate(LEVELS):
        base = 120_000 + level_i * 38_000
        for loc in LOCATIONS:
            # thin the tail deliberately: senior + smaller metros are sparse
            n_companies = {
                ("L6", "austin"): 2,
                ("L6", "denver"): 1,
                ("L5", "austin"): 4,
            }.get((level, loc), rng.randint(6, 11))
            for c in range(n_companies):
                for _ in range(rng.randint(1, 3)):
                    out.append(
                        Observation(
                            company=f"contributor-{c:02d}",
                            level=level,
                            location=loc,
                            base=int(rng.gauss(base, 18_000)),
                        )
                    )
    return out


def _table(k: int):
    return build(sample_market(), k=k)


def _cell_dict(c) -> dict:
    return {
        "level": c.level,
        "location": c.location,
        "n": c.n,
        "companies": c.companies,
        "p25": c.p25,
        "p50": c.p50,
        "p75": c.p75,
        "suppressed": c.suppressed,
        "reason": c.reason,
    }


# -- REST -----------------------------------------------------------------


def up(request):
    return JsonResponse({"status": "ok", "k": DEFAULT_K})


def benchmarks(request):
    try:
        k = int(request.GET.get("k", DEFAULT_K))
    except ValueError:
        return JsonResponse({"error": "k must be an integer"}, status=400)
    if not 1 <= k <= 50:
        return JsonResponse({"error": "k must be between 1 and 50"}, status=400)

    table = _table(k)
    leaks = audit(table)
    return JsonResponse(
        {
            "k": k,
            "cells": [_cell_dict(c) for c in table.cells],
            "published": len(table.published()),
            "suppressed": len(table.suppressed()),
            # Reported rather than assumed: the response carries the result of
            # re-auditing the exact table being returned.
            "audit": leaks,
            "safe": leaks == [],
        }
    )


# -- GraphQL --------------------------------------------------------------

CellType = GraphQLObjectType(
    "Cell",
    {
        "level": GraphQLField(GraphQLString),
        "location": GraphQLField(GraphQLString),
        "n": GraphQLField(GraphQLInt),
        "companies": GraphQLField(GraphQLInt),
        "p25": GraphQLField(GraphQLInt),
        "p50": GraphQLField(GraphQLInt),
        "p75": GraphQLField(GraphQLInt),
        "suppressed": GraphQLField(GraphQLBoolean),
        "reason": GraphQLField(GraphQLString),
    },
)

TableType = GraphQLObjectType(
    "Table",
    {
        "k": GraphQLField(GraphQLInt),
        "cells": GraphQLField(GraphQLList(CellType)),
        "audit": GraphQLField(GraphQLList(GraphQLString)),
        "safe": GraphQLField(GraphQLBoolean),
    },
)


def _resolve_benchmarks(root, info, k=DEFAULT_K, level=None, location=None):
    table = _table(k)
    leaks = audit(table)
    cells = table.cells
    # Filters narrow what is *returned*, never what is suppressed. Suppression is
    # decided on the whole table first, so a caller cannot widen their view by
    # slicing it -- asking only for the thin cell still gets a suppressed cell.
    if level:
        cells = [c for c in cells if c.level == level]
    if location:
        cells = [c for c in cells if c.location == location]
    return {
        "k": k,
        "cells": [_cell_dict(c) for c in cells],
        "audit": leaks,
        "safe": leaks == [],
    }


schema = GraphQLSchema(
    query=GraphQLObjectType(
        "Query",
        {
            "benchmarks": GraphQLField(
                TableType,
                args={
                    "k": GraphQLArgument(GraphQLInt),
                    "level": GraphQLArgument(GraphQLString),
                    "location": GraphQLArgument(GraphQLString),
                },
                resolve=_resolve_benchmarks,
            )
        },
    )
)


def graphql_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST a JSON body with a query"}, status=405)
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)

    result = graphql_sync(schema, body.get("query") or "", variable_values=body.get("variables"))
    out: dict = {}
    if result.errors:
        out["errors"] = [str(e) for e in result.errors]
    if result.data is not None:
        out["data"] = result.data
    return JsonResponse(out, status=400 if result.errors else 200)


def index(request):
    return HttpResponse((BASE / "banding" / "index.html").read_text(), content_type="text/html")


urlpatterns = [
    path("", index),
    path("up", up),
    path("api/benchmarks", benchmarks),
    path("graphql", graphql_view),
]

application = None  # set in wsgi.py
