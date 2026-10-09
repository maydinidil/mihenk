"""The command line: `mihenk capture URL` captures one page and prints where it went (design §8.3).

It runs the same capture code as a run will, without the window, the server or an LLM. Output is
one line per state: label, status, detail and the snapshot folder, separated by tabs. The exit
code is 0 when every state was captured, 1 when any was not or the capture itself failed, 2 when
the command line (the URL included) or the http client set-up is wrong, and 130 after Ctrl+C.

`mihenk install-browser` downloads Playwright's own Chromium into the data folder, after asking
(design §17). `mihenk _playwright-install` is not for people: it is how that download reaches
Playwright's own command line, from source and from the frozen app alike.
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
from playwright.__main__ import main as playwright_main
from playwright.sync_api import Browser, sync_playwright
from playwright.sync_api import Error as PlaywrightError
from pydantic import ValidationError

from mihenk.app.paths import default_data_dir
from mihenk.capture.browser import (
    BrowserUnavailable,
    browsers_dir,
    has_downloaded_chromium,
    install_chromium,
    launch_browser,
    start_playwright_env,
)
from mihenk.capture.fetch import fetch_robots, make_client
from mihenk.capture.models import SAFE_SEGMENT, CaptureStatus, Method
from mihenk.capture.pace import Pace, host_key, idna_host
from mihenk.capture.recipe import Recipe, State
from mihenk.capture.render import RenderSettings
from mihenk.capture.robots import RobotsFetch, RobotsGate
from mihenk.capture.run import CaptureResult, PageSpec, RunContext, capture_page, is_http_url
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
    install = commands.add_parser(
        "install-browser",
        help="download Playwright's Chromium, for a computer without Chrome or Edge",
        description="Download Playwright's own Chromium (about 200 MB) into the data folder. "
        "It is only needed if Chrome and Edge are not installed.",
    )
    install.add_argument(
        "--yes", action="store_true", help="download without asking first (for scripts)"
    )
    install.add_argument("--data-dir", type=Path, help="use this data folder")
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


def _close_quietly(browser: Browser) -> None:
    with contextlib.suppress(PlaywrightError):
        browser.close()


def _capture_in_browser(spec: PageSpec, ctx: RunContext, data_dir: Path) -> list[CaptureResult]:
    """Starts Playwright for a render method, captures, and always closes the browser.

    An installed Chrome or Edge is used first, then a Chromium downloaded into the data folder
    (`mihenk install-browser`). No browser at all is a result (`browser_unavailable` per state),
    not an error. After Ctrl+C nothing is closed: Playwright's sync calls hang while the
    interrupt is in flight, and its driver process exits with this one.
    """
    start_playwright_env(data_dir)  # before the session starts: its driver reads this once
    with contextlib.ExitStack() as cleanup:
        pw = cleanup.enter_context(sync_playwright())
        try:
            try:
                launched = launch_browser(pw, allow_downloaded=True)
            except BrowserUnavailable:
                return capture_page(spec, ctx)
            cleanup.callback(_close_quietly, launched.browser)
            ctx.browser = launched.browser
            return capture_page(spec, ctx)
        except KeyboardInterrupt:
            cleanup.pop_all()  # drop the cleanup, unrun
            raise


def _capture(args: argparse.Namespace) -> int:
    try:
        recipe = _build_recipe(args.method, args.state)
    except ValueError as exc:
        _emit(sys.stderr, f"mihenk capture: error: {exc}")
        return 2
    if not is_http_url(args.url):
        # Before Playwright or an http client starts: a render run would open a browser for it.
        _emit(sys.stderr, f"mihenk capture: error: not a valid http(s) URL: {args.url[:200]!r}")
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

        def pace_request(url: str) -> None:
            pace.wait(host_key(url))

        def fetch_robots_paced(url: str) -> RobotsFetch:
            # Every request robots.txt takes, its redirect hops included, is paced like a page.
            return fetch_robots(client, url, before_request=pace_request)

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
                results = _capture_in_browser(spec, ctx, data_dir)
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


def _exit_code(code: object) -> int:
    """The int a `SystemExit` stands for: no code is 0, a message or anything else is 1."""
    if code is None:
        return 0
    return code if isinstance(code, int) else 1


def _printable(text: str) -> str:
    """The text with each character the console cannot show replaced by a question mark.

    For `input()`'s prompt, which writes it to the console as it is. The data folder is in the
    prompt, and a Windows user folder can hold letters a redirected code page cannot encode.
    """
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    return text.encode(encoding, "replace").decode(encoding)


def _asked_yes(question: str) -> bool:
    """Asks on the console; only y or yes (any case) is a yes. No console to ask on is a no."""
    try:
        answer = input(_printable(question + " "))
    except (EOFError, RuntimeError):  # RuntimeError: a windowed build has no sys.stdin
        return False
    return answer.strip().lower() in {"y", "yes"}


def _install_browser(args: argparse.Namespace) -> int:
    data_dir: Path = args.data_dir or default_data_dir()
    folder = browsers_dir(data_dir)
    if not args.yes:
        question = (
            f"Download Playwright's Chromium (about 200 MB) into {folder}? "
            "It is only needed if Chrome and Edge are not installed. [y/N]"
        )
        if not _asked_yes(question):
            _emit(sys.stdout, "Nothing was downloaded.")
            return 0
    _emit(sys.stdout, f"Downloading Playwright's Chromium into {folder} ...")
    try:
        code = install_chromium(data_dir)
    except OSError as exc:  # the program could not even start
        _emit(
            sys.stderr,
            f"mihenk install-browser: failed: {_one_line(str(exc)) or type(exc).__name__}",
        )
        return 1
    if code != 0:
        _emit(sys.stderr, f"mihenk install-browser: failed: the download ended with code {code}")
        return 1
    if not has_downloaded_chromium(data_dir):
        # An exit code of 0 is not proof: only a Chromium that Playwright marked complete counts.
        _emit(
            sys.stderr,
            "mihenk install-browser: failed: the download did not finish "
            f"(no complete Chromium in {folder})",
        )
        return 1
    _emit(sys.stdout, "Done. mihenk uses it when Chrome and Edge are not installed.")
    return 0


# The only command lines mihenk needs from Playwright's own: the Chromium download, and its version
# (a check that the bundled driver runs). Anything else is refused: a bare `install`, for one,
# would fill Playwright's global cache with every browser.
_PLAYWRIGHT_COMMANDS = frozenset(
    {("install", "chromium"), ("install", "chromium", "--no-shell"), ("--version",)}
)


def _playwright_install(rest: Sequence[str]) -> int:
    """Runs Playwright's own command line with `rest`; `install_command` is what calls this.

    Playwright's `main()` reads `sys.argv[1:]` and always ends in `sys.exit(code)`.
    """
    if tuple(rest) not in _PLAYWRIGHT_COMMANDS:
        _emit(
            sys.stderr,
            "mihenk _playwright-install: error: only 'install chromium [--no-shell]' "
            "and '--version' are accepted",
        )
        return 2
    saved = sys.argv
    sys.argv = ["playwright", *rest]
    try:
        playwright_main()
    except SystemExit as exc:
        return _exit_code(exc.code)
    finally:
        sys.argv = saved
    return 0


def main(argv: Sequence[str]) -> int:
    try:
        return _run_command(argv)
    except KeyboardInterrupt:
        # Ctrl+C: no traceback, and no Playwright cleanup (see _capture_in_browser).
        _emit(sys.stderr, "Stopped.")
        return 130


def _run_command(argv: Sequence[str]) -> int:
    if argv and argv[0] == "_playwright-install":
        # Not an argparse command: the rest of the line belongs to Playwright, whose options
        # (--no-shell and the like) argparse would refuse, and it stays out of --help.
        return _playwright_install(argv[1:])
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:  # --help, and a command line argparse refuses (code 2)
        return _exit_code(exc.code)
    if args.command == "capture":
        return _capture(args)
    if args.command == "install-browser":
        return _install_browser(args)
    raise AssertionError(f"unhandled command {args.command!r}")  # pragma: no cover
