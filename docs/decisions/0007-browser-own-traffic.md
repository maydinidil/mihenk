# 0007: The browser's own traffic during captures

Date: 2026-10-12. Status: decided (option A, Aydin's go 2026-10-12).

## The question

mihenk promises no network call except tracked pages, the chosen LLM provider and the update
check (§3 row 6, §14). The stage 1 final review found that branded Chrome, driven by Playwright,
connects to Google's own services while mihenk uses it, and that Edge would do the same with
Microsoft's. Option A: launch the browser with the switches that turn its own services off,
measure that a capture then reaches only the page's own hosts, and name whatever is left.

## How it was measured

| Step | What was done |
|---|---|
| Launch | `launch_browser(pw, allow_downloaded=True)`, as `mihenk capture` calls it, not confined, plus `--log-net-log` with `--net-log-capture-mode=Default` |
| Page | A small page of our own, served on 127.0.0.1. Nothing else was opened |
| Run | The page stayed open about 60 seconds, then one state was rendered with `render_states`, then the browser closed |
| Net log | Every host name the browser's network service looked up, requested or connected to that is not on this machine, with the URL path |
| Cross-check | Every 4 to 5 seconds, the TCP connections of the browser's processes (`Get-NetTCPConnection` by process id; the process tree and the final command line from `Get-CimInstance Win32_Process`) |
| Finding the switches | Confined runs (the tests' confinement on). A confined browser still starts each request, so the net log shows the attempt while nothing leaves |
| Versions | Chrome 154.0.8037.98, Edge 155.0.4283.45, Playwright 1.63.0, Windows 11 |

Six runs could reach outside this machine: the baseline and the after run for each browser, which
were not confined, and two confined Edge runs in which Edge's main process still connected out
(see "What remains"). The task report lists each one.

## Chrome: before and after

| Host | What it is | Before | After |
|---|---|---|---|
| accounts.google.com | The sign-in account check (`/ListAccounts`) | Connected | Not contacted |
| android.clients.google.com | Push messaging (GCM): check-in and six registrations (`/checkin`, `/c2dm/register3`) | Connected | Tried; stopped at the name lookup, inside the browser |
| mtalk.google.com, port 5228 | Push messaging connection, kept open | Connected | Not contacted |
| clients2.google.com | Clock check (`/time/1/current`) | Connected | Not contacted |
| update.googleapis.com | Component update check for the on-device AI model list | Connected | Not contacted |
| edgedl.me.gvt1.com | The download of that component | Connected | Not contacted |
| www.google.com | AI Mode check (`/async/folae`, which sends locale and country) and an early connection to the search engine | Connected | Not contacted |
| www.gstatic.com | Safe Browsing key fetch (`/ohttp_gateway/hpke_public_keys/...`) | Connected | Not contacted |
| wpad (a local network name) | Windows proxy auto-detection | Looked up | Looked up |

TCP connections outside this machine: 8 Google addresses before, none after.

## Edge: before and after

| Host | What it is | Before | After |
|---|---|---|---|
| edge.microsoft.com | Clock, component updates, the configuration service, the Microsoft account check, the ad blocklist | Connected | Ad blocklist tried; stopped at the name lookup. The rest not contacted |
| substrate.office.com | Silent sign-in with the Windows account, then that account's profile and photo | Connected | Not contacted |
| mss.office.com | Copilot eligibility for that account | Connected | Not contacted |
| www.bing.com | Bing sign-in, an early search connection, shopping settings, the shopping domain list | Connected | Shopping settings and domain list still connected |
| edge-consumer-static.azureedge.net | Mouse gesture configuration | Connected | Not contacted |
| A Microsoft address, from Edge's main process | Not identified (see "What remains") | Connected | Connected |
| wpad (a local network name) | Windows proxy auto-detection | Looked up | Looked up |

TCP connections outside this machine: 8 addresses before (Microsoft's services and Bing), 2 after.

## The switches

Every launch gets these, real captures and tests alike. Chrome and Edge keep only the last
`--disable-features` and the last `--host-resolver-rules` on a command line, so each is one merged
switch. Playwright passes its own `--disable-features`; mihenk leaves that one out by its exact
text and passes Playwright's list and its own in one switch. The final command line was read from
the running browser: one `--disable-features`, one `--host-resolver-rules`.

| Switch | Turns off | Where it was seen |
|---|---|---|
| Feature `NetworkTimeServiceQuerying` | The clock check | clients2.google.com, edge.microsoft.com |
| Feature `SafeBrowsingHashPrefixRealTimeLookups` | Safe Browsing's real-time check and its key fetch at start | www.gstatic.com |
| Feature `AimEnabled` | Google AI Mode in the address bar, and its check | www.google.com |
| Feature `PreconnectToSearch` | The early connection to the default search engine | www.google.com, www.bing.com |
| Feature `msImplicitSignin` | Edge signing in with the Windows account, and the profile, Copilot and Bing sign-in calls after it | substrate.office.com, mss.office.com, edge.microsoft.com, www.bing.com |
| Features `msUXConfigService`, `msUXConfigServiceV3` | Edge's configuration service | edge.microsoft.com |
| Feature `msEdgeMouseGestureSupported` | Edge's mouse gesture configuration | edge-consumer-static.azureedge.net |
| `--gaia-url=http://127.0.0.1:9/` | Chrome's account check: it goes to port 9 on this machine, which Chrome refuses (`ERR_UNSAFE_PORT`). Pages that load accounts.google.com are not affected | accounts.google.com |
| `--component-updater=url-source=http://127.0.0.1:9/` | Component update checks, sent the same way | update.googleapis.com, edgedl.me.gvt1.com, edge.microsoft.com |
| Host rule for android.clients.google.com and mtalk.google.com | Push messaging. No switch turns it off in Chrome 154, and its addresses are no longer command-line settings. No web page loads these two names | android.clients.google.com, mtalk.google.com |
| Host rule for edge.microsoft.com | Edge's ad blocklist, which has no switch, and any other call to Edge's service host. No web page loads this name | edge.microsoft.com |
| `--allow-browser-signin=false` | Signing in to the browser | No difference in these runs. Kept so a page with a Google or Microsoft sign-in cannot sign the browser in |
| `--disable-domain-reliability` | Error reports about Google sites, sent to Google | Not triggered by the test page; a real page with a failing Google font or script would |
| `--no-pings` | Link pings (`<a ping>`) when a link is clicked | Not triggered by the test page |
| `--disable-sync`, `--disable-background-networking`, `--disable-component-update` | Sync, background requests, component updates | Playwright passes these too. They are repeated so the promise does not rest on Playwright's list |

When the tests' confinement is on (`MIHENK_BROWSER_LOOPBACK_ONLY=1`), its rule
`MAP * ~NOTFOUND , EXCLUDE 127.0.0.1` follows the service rules in the same switch, and the dead
proxy stays.

## What remains

| Browser | What | Why it stays |
|---|---|---|
| Both | A name lookup of `wpad` | Windows has "Automatically detect settings" on, and the browser follows the system proxy setting, which users behind a company proxy need. The lookup goes to the local network's name server and carries no page data |
| Edge | www.bing.com: shopping settings and the shopping domain list, at start | No switch found in Edge 155. Only a group policy turns Edge's shopping off, and that would change the user's own Edge too. www.bing.com cannot get a host rule, because pages load it |
| Edge | A connection from Edge's main process to a Microsoft address (in the 52.97.x, 52.98.x and 40.99.x ranges that substrate.office.com resolved to in the baseline) | Edge opens it outside its network stack, so no network switch, host rule or proxy setting reaches it. It stayed with sign-in turned off. Not identified without more outside traffic; most likely Edge's Windows account layer (unconfirmed) |
| Both, with a proxy set in Windows | The three host rules may not apply | With a proxy, the browser hands host names to the proxy instead of looking them up. Not measured: this machine has no proxy |

Edge is used only when Chrome is not installed (§17).

The Edge connection also happened in both confined Edge runs, so the tests' confinement does not
fully hold for Edge. The tests launch Chrome first. On a machine with Edge only, the browser tests
would make that connection.

## For the privacy notice (stage 6)

"When Chrome is not installed, mihenk uses Microsoft Edge, and Edge itself contacts Microsoft while
a capture runs (Bing for its shopping settings, and a Microsoft service for your Windows account).
mihenk cannot switch this off. Windows may also look up the name 'wpad' on your local network to
find a proxy."

## Keeping it true

| Change | What to do |
|---|---|
| Playwright upgrade | `test_the_browser_gets_one_disable_features_and_one_host_rules_switch` fails if Playwright's own list changed. Copy the new list into `_PLAYWRIGHT_DISABLED_FEATURES` |
| A new major Chrome or Edge | Feature names are not a stable interface; a renamed feature brings its service back without an error. Repeat this measurement |

## Check

`MIHENK_REQUIRE_BROWSER=1 uv run pytest -q -p no:cacheprovider` passes, including
`tests/unit/test_browser_install.py` (the switches, the merged `--disable-features`, the merged
host rules with and without the confinement) and `tests/integration/test_browser.py` (the real
command line).
