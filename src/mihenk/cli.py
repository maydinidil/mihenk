"""The command line: `mihenk capture URL` captures one page and prints where it went (design §8.3).

It runs the same capture code as a run will, without the window, the server or an LLM. Output is
one line per state: label, status, detail and the snapshot folder, separated by tabs. The exit
code is 0 when every state was captured, 1 when any was not or the capture itself failed, and 2
when the command line or the http client set-up is wrong.
"""

from __future__ import annotations

import argparse
import contextlib
import locale
import re
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO
from urllib.parse import urlsplit

import httpx2 as http
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright
from pydantic import ValidationError

from mihenk.app.paths import default_data_dir
from mihenk.capture.browser import BrowserUnavailable, launch_browser
from mihenk.capture.fetch import fetch_robots, make_client
from mihenk.capture.models import SAFE_SEGMENT, CaptureStatus, Method
from mihenk.capture.pace import Pace, host_key, idna_host
from mihenk.capture.recipe import Recipe, State
from mihenk.capture.render import RenderSettings
from mihenk.capture.robots import RobotsFetch, RobotsGate
from mihenk.capture.run import CaptureResult, PageSpec, RunContext, capture_page
from mihenk.capture.snapshot import new_run_id

# Requests to one site are at least this far apart (design §8.2).
PACE_INTERVAL_S = 2.0
UNKNOWN_COUNTRY = "ZZ"
_MAX_DETAIL_CHARS = 300


def region_from_locale(name: str | None) -> str:
    """The two-letter region of a locale name such as "en_NL", "en-NL" or "tr_TR.UTF-8".

    The last part of the name, after any ".encoding" or "@modifier", upper-cased, and only when it
    is exactly two ASCII letters. Anything else gives "ZZ" (unknown): a name without a region ("C"),
    one with a number ("es-419") or a script ("zh-Hant"), and Windows' long English names, whose
    last part is a country spelled out ("English_Netherlands").
    """
    if not name:
        return UNKNOWN_COUNTRY
    base = name.split(".", 1)[0].split("@", 1)[0]
    parts = re.split(r"[_-]", base)
    region = parts[-1] if len(parts) > 1 else ""
    if len(region) == 2 and region.isascii() and region.isalpha():
        return region.upper()
    return UNKNOWN_COUNTRY


def system_locale_name() -> str | None:
    """The user's locale name: "en-NL" on Windows, "en_NL" elsewhere, or None when unknown.

    On Windows `locale.getlocale()` returns a long English name ("English_Netherlands"), so the
    system call that returns the BCP 47 name is used instead.
    """
    if sys.platform == "win32":
        import ctypes

        buffer = ctypes.create_unicode_buffer(85)  # LOCALE_NAME_MAX_LENGTH
        if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, len(buffer)) > 0:
            return buffer.value
        return None
    try:
        return locale.getlocale()[0]
    except ValueError:  # "unknown locale", as macOS reports for some settings
        return None


def default_key(url: str) -> str:
    """A page key from the URL's host (IDNA, no port) and path: lower case, [a-z0-9-], up to 64."""
    try:
        raw = f"{idna_host(url)}{urlsplit(url).path}".lower()
    except ValueError:  # a URL the capture will refuse anyway
        raw = ""
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:64].strip("-") or "page"
    if SAFE_SEGMENT.fullmatch(slug) is None:  # a name Windows reserves, such as "nul"
        slug = f"page-{slug}"[:64].rstrip("-")
    return slug


def _key_argument(value: str) -> str:
    if SAFE_SEGMENT.fullmatch(value) is None:
        raise argparse.ArgumentTypeError(
            "a key is 1 to 64 characters: lower-case letters, digits, - and _, "
            "starting with a letter or digit"
        )
    return value


def _country_argument(value: str) -> str:
    if len(value) != 2 or not value.isascii() or not value.isalpha():
        raise argparse.ArgumentTypeError("a country is two letters, such as NL")
    return value.upper()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mihenk", description="mihenk command line.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    capture = commands.add_parser(
        "capture",
        help="capture one page and print where the snapshot went",
        description="Capture one page: robots.txt, pacing, fetch or render, snapshot.",
    )
    capture.add_argument("url", help="the page to capture (http or https)")
    capture.add_argument("--key", type=_key_argument, help="page key (default: from host and path)")
    capture.add_argument(
        "--method",
        choices=[method.value for method in Method],
        default=Method.FETCH.value,
        help="fetch the HTML, render it in the browser, or render and operate it (default: fetch)",
    )
    capture.add_argument(
        "--state",
        action="append",
        metavar="LABEL[=CLICK_TEXT]",
        help="a state to capture; LABEL=TEXT first clicks the exact text TEXT "
        "(repeat for several; render_interact only; default: one state called default)",
    )
    capture.add_argument(
        "--ignore-robots", action="store_true", help="do not check robots.txt (a per-brand choice)"
    )
    capture.add_argument(
        "--country",
        type=_country_argument,
        help="the country the capture is made from (default: this computer's region)",
    )
    capture.add_argument("--data-dir", type=Path, help="use this data folder")
    return parser


def _build_recipe(method: str, state_arguments: Sequence[str] | None) -> Recipe:
    """The recipe the options describe. Raises ValueError with a message for the person."""
    states: list[State] = []
    for argument in state_arguments or ["default"]:
        label, equals, text = argument.partition("=")
        actions = [{"kind": "click_text", "text": text}] if equals else []
        try:
            states.append(State.model_validate({"label": label, "actions": actions}))
        except ValidationError as exc:
            raise ValueError(f"--state {argument!r}: {_pydantic_message(exc)}") from exc
    try:
        return Recipe(method=Method(method), states=states)
    except ValidationError as exc:
        raise ValueError(
            f"--method {method} with these --state options: {_pydantic_message(exc)}"
        ) from exc


def _pydantic_message(exc: ValidationError) -> str:
    return exc.errors()[0]["msg"].removeprefix("Value error, ")


def _one_line(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) > _MAX_DETAIL_CHARS:
        return collapsed[: _MAX_DETAIL_CHARS - 3] + "..."
    return collapsed


def _emit(stream: TextIO | None, line: str) -> None:
    """Writes a line. A console that cannot show a character (a code page, not UTF-8) gets a
    question mark in its place, not a traceback. No stream (a windowed build) writes nothing."""
    if stream is None:
        return
    try:
        stream.write(line + "\n")
    except UnicodeEncodeError:
        encoding = stream.encoding or "ascii"
        stream.write(line.encode(encoding, "replace").decode(encoding) + "\n")


def _result_line(result: CaptureResult) -> str:
    folder = str(result.snapshot.path) if result.snapshot is not None else "-"
    return "\t".join((result.state_label, result.status.value, _one_line(result.detail), folder))


def _capture_in_browser(spec: PageSpec, ctx: RunContext) -> list[CaptureResult]:
    """Starts Playwright for a render method, captures, and always closes the browser.

    Until Task 1.10 only an installed Chrome or Edge is used. No browser at all is a result
    (`browser_unavailable` per state), not an error.
    """
    with sync_playwright() as pw:
        try:
            launched = launch_browser(pw)
        except BrowserUnavailable:
            return capture_page(spec, ctx)
        try:
            ctx.browser = launched.browser
            return capture_page(spec, ctx)
        finally:
            with contextlib.suppress(PlaywrightError):
                launched.browser.close()


def _capture(args: argparse.Namespace) -> int:
    try:
        recipe = _build_recipe(args.method, args.state)
    except ValueError as exc:
        _emit(sys.stderr, f"mihenk capture: error: {exc}")
        return 2
    data_dir: Path = args.data_dir or default_data_dir()
    country: str = args.country or region_from_locale(system_locale_name())
    spec = PageSpec(args.key or default_key(args.url), args.url, recipe, not args.ignore_robots)
    settings = RenderSettings()
    # One client per run, closed after it: its cookies must not reach another brand or run (§8.3).
    # A malformed proxy variable (HTTP_PROXY and the like) fails here, before any request: with
    # an address httpx2 cannot read (InvalidURL), a scheme it does not know (ValueError) or a
    # SOCKS proxy without the package for it (ImportError).
    try:
        client = make_client(settings.locale)
    except (ImportError, ValueError, http.InvalidURL) as exc:
        _emit(
            sys.stderr,
            f"mihenk capture: error: cannot set up the http client: {_one_line(str(exc))}",
        )
        return 2
    try:
        pace = Pace(PACE_INTERVAL_S)

        def fetch_robots_paced(url: str) -> RobotsFetch:
            pace.wait(host_key(url))
            return fetch_robots(client, url)

        ctx = RunContext(
            run_id=new_run_id(datetime.now(UTC)),
            snapshots_root=data_dir / "snapshots",
            collection_country=country,
            robots=RobotsGate(fetch_robots_paced),
            pace=pace,
            http_client=client,
            browser=None,
            render=settings,
            now=lambda: datetime.now(UTC),
        )
        try:
            if recipe.method is Method.FETCH:
                results = capture_page(spec, ctx)
            else:
                results = _capture_in_browser(spec, ctx)
        except Exception as exc:
            # A snapshot path that is too long (ValueError), a disk that is full (OSError)...
            message = _one_line(str(exc)) or type(exc).__name__
            _emit(sys.stderr, f"mihenk capture: failed: {type(exc).__name__}: {message}")
            return 1
    finally:
        client.close()
    for result in results:
        _emit(sys.stdout, _result_line(result))
    return 0 if all(result.status is CaptureStatus.OK for result in results) else 1


def main(argv: Sequence[str]) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:  # --help, and a command line argparse refuses (code 2)
        code = exc.code
        if code is None:
            return 0
        return code if isinstance(code, int) else 1
    if args.command == "capture":
        return _capture(args)
    raise AssertionError(f"unhandled command {args.command!r}")  # pragma: no cover
