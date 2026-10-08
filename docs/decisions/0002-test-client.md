# 0002: HTTP client for the test client

Date: 2026-10-09. Status: decided.

## The question

FastAPI's `TestClient` is Starlette's, and it needs an HTTP client package to run. Task 0.2
installed `httpx` in the dev group. With Starlette 1.7 that works, but every test run prints
`StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install
httpx2 instead.`

## The decision

Add `httpx2` to the dev group. Keep `httpx` there too.

| Package | Why |
|---|---|
| `httpx2` (new, `>=2.13.1`) | The package Starlette 1.7 asks for. It removes the warning. It is also the HTTP client the design picks for capture, so the app ends up with one HTTP stack. |
| `httpx` (kept) | The Task 0.6 server-thread test imports `httpx` directly. Removing it would break that test. Drop it when that test moves to `httpx2`. |

`httpx2` brings in `httpcore2` (BSD-3-Clause) and `truststore` (MIT). `httpx2` itself is
BSD-3-Clause. None of the three is GPL, AGPL or LGPL.

## What it does not change

Only the dev group changes. The runtime dependencies are untouched. The capture task adds `httpx2`
to the runtime dependencies with its own floor, and the dev-group line can go at that point.

## Check

`uv run pytest tests/unit/test_security.py -v` passes with no warnings.
