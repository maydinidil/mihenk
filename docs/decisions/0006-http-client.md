# 0006: HTTP client for plain capture

Date: 2026-10-09. Status: decided.

## The question

The `fetch` capture method (§8.3) and the `robots.txt` read (§8.2) need an HTTP client. Which
package, and does its API do what the plan's code needs?

## The decision

Use `httpx2`, imported as `import httpx2 as http`. Move it from the dev group to the runtime
dependencies, as decision 0002 said capture would. Keep `httpx` in the dev group, because
`tests/integration/test_server_thread.py` and two other test files import it directly.

| Where | Line | Why |
|---|---|---|
| Runtime `dependencies` | `httpx2>=2.13.1,<3` | The floor is the version Task 0.2 locked and the one read for this decision. §22 names no higher floor. The cap follows the other lines in the file (a major version is a deliberate step) |
| Dev group | `httpx2` removed | It now arrives as a runtime dependency. Starlette's `TestClient` still finds it, so the deprecation warning stays gone |
| Dev group | `httpx>=0.28` kept | Still imported by three test files |

## What was checked

Everything below was read from the installed package (`httpx2` 2.13.1: its README and its
source), not from the web. Nothing was fetched from a live site.

| The plan needs | What `httpx2` does | Matches? |
|---|---|---|
| Import name | `httpx2` | Yes |
| `Client(headers=, timeout=, follow_redirects=, max_redirects=)` | All four are keyword arguments of `Client` | Yes |
| Redirect limit | The default is 20, so `make_client` sets 5. With `max_redirects=5` the fifth redirect is followed and the sixth raises `TooManyRedirects`. The fetch code does not use this: it follows redirects itself (see "How time, size and redirects are bounded") with the same limit | Yes, tested at 5 and 6 |
| `client.stream("GET", url)` with `iter_bytes()` | `stream` is a context manager that returns before the body is read. `iter_bytes()` yields the decoded body (gzip, deflate) in chunks, so a size cap counts decoded bytes | Yes |
| Closing a response early (leaving the `with`, or `response.close()` on a redirect) | Closes the connection without reading the rest | Yes, tested with bodies that would never end |
| `TimeoutException` | A subclass of `TransportError` | Yes |
| `TooManyRedirects` | A subclass of `RequestError`, **not** of `TransportError`, so it needs its own `except` | Yes |
| `TransportError` | Connection, read and protocol errors | Yes |

Three things the plan's code did not cover, found while reading the source. The fetch code now
handles each, with a test:

| Found | Why it matters | Handled by |
|---|---|---|
| `DecodingError` (a body that claims gzip and is not) is a `RequestError`, not a `TransportError` | It is raised while the body is read, after the status line. `fetch_robots` must never raise, and `fetch_page` should report it as a `FetchFailure` | Both functions catch it |
| `InvalidURL` derives from plain `Exception` | A bad port or bracket in a recipe URL would crash a capture | Both functions catch it |
| A host such as `a..b` raises a bare `UnicodeError` from the socket layer | Same | Both functions catch it |

## What it brings

`httpx2` is BSD-3-Clause. Its runtime dependencies are `httpcore2` (BSD-3-Clause), `anyio` (MIT),
`idna` (BSD-3-Clause) and `truststore` (MIT). `h11` (MIT) comes through `httpcore2`. None is GPL,
AGPL or LGPL. `uv run python tools/check_licenses.py` exits 0.

Behaviours to know about:

| Behaviour | Effect on mihenk |
|---|---|
| TLS uses the operating system's trust store (`truststore`) | A company laptop whose own certificate authority is installed works without extra setup |
| `trust_env` is on by default | `HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY` apply, so a user behind a proxy captures too. On a test machine with a proxy variable set, the loopback tests could be sent to that proxy, and the network guard would stop them (not tried here: this machine has none set) |
| Timeouts apply to each connect, read and write, not to the whole request | A server that sends one byte every few seconds is never cut off by `timeout_s`. Both fetch functions therefore take a `deadline_s` (below) |
| `Client` follows redirects by reading each redirect's body in full first | A 3xx with a huge or endless body sat outside the size caps and the deadline (a 100 MiB body was read, with about 200 MiB peak memory). The fetch code follows redirects itself and never reads a redirect's body |

## How time, size and redirects are bounded

| Bound | Pages (`fetch_page`) | `robots.txt` (`fetch_robots`) |
|---|---|---|
| Time for the whole fetch, first request to last byte | `deadline_s`, default 90 s. Passed: `FetchFailure(TIMEOUT, "deadline of N s passed")` | `deadline_s`, default 30 s. Passed: `RobotsFetch(None, None, "unreachable: deadline passed")` |
| Where the deadline is checked | Before every request, and after every chunk of body | The same |
| Size | 15 MiB after decompression, then `FetchFailure(TOO_LARGE)` | Reading stops at 512 KiB; the rest is not read |
| Redirects | At most 5 are followed; the sixth fails as `HTTP_ERROR` "more than 5 redirects" | At most 5; the sixth gives `RobotsFetch(None, None, "unreachable: more than 5 redirects")` |

How a redirect is followed: the request is sent with `follow_redirects=False` and `stream=True`.
On a 3xx with a `Location`, the response is closed without reading its body, and the next request
is the one httpx2 prepared (`response.next_request`). The answer that is not a redirect is the
one whose body is read. `final_url` is that response's URL.

A single read can still block for up to `timeout_s` after the deadline has passed, so a fetch ends
within `deadline_s` plus about one `timeout_s`.

## Not checked here

- `openai` and `anthropic` are not installed yet (Stage 2). §6 says both depend on `httpx2`. Check
  their `httpx2` bounds when they are added; the `<3` cap here must not conflict with them.
- A live site. Only `LocalSite` on 127.0.0.1 was used, as the plan requires.

## Check

`uv run pytest tests/integration/test_fetch.py tests/integration/test_fetch_limits.py tests/integration/test_robots_fetch.py tests/unit/test_decode.py -v`
passes, and `uv run python tools/check_licenses.py` exits 0.
