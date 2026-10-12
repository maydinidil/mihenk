# 0008: The first live capture

Date: 2026-10-12. Status: done (stage 1's last "done" check, run at Aydin's request).

## What was captured

| Item | Value |
|---|---|
| Page | https://www.moneybird.nl/prijzen/ (a Dutch accounting service's pricing page, with a "Betaal per jaar" switch) |
| Browser | Chrome 154, launched with the switches from decision 0007 |
| Country | `NL` (passed with `--country`; this computer's Windows region gives `US`) |
| robots.txt | Allowed every time it was checked |
| Snapshots | Kept in a scratch folder on this computer only. No page from the site is committed |

## The runs

Every run went through mihenk's own robots.txt check and its 2 second pacing per site, except
the one probe noted below.

| # | How | Result |
|---|---|---|
| 1 | `mihenk capture <URL>` (fetch) | `ok`. HTTP 200, UTF-8, `html_lang` nl, the euro sign, three JSON-LD blocks, no VAT phrase (the page states none beside its prices) |
| 2 | `mihenk capture <URL> --method render_interact --state annual --state monthly="Betaal per jaar"` | `annual` ok. `monthly` `action_failed` after 30 s: the text "Betaal per jaar" is a label beside the switch, not the switch, and the click never landed. Recorded, not hung |
| 3 | The same capture through the recipe API, `monthly` clicking `button[role="switch"]` | `annual` ok. `monthly` `action_failed`: the site's cookie dialog (`<mb-cookie-modal-component>`) lies over the page and catches every click |
| 4 | One page load outside mihenk's gate, to read the cookie dialog's buttons (they are in a shadow root, so neither the HTML nor the text holds them) | Buttons: "Akkoord", "Voorkeuren instellen", "Alles accepteren", "Voorkeuren opslaan" |
| 5 | The recipe again, `monthly` = click "Voorkeuren instellen", click "Voorkeuren opslaan" (the least consent), click the switch | Both states `ok`, HTTP 200, every file hash in `meta.json` matches the file |

## What the snapshot showed

| Part | Yearly state | Monthly state |
|---|---|---|
| Screenshot | Start € 15, Groei € 29, Compleet € 41 per month, each with a "Bespaar ... per jaar" badge | Start € 18, Groei € 35, Compleet € 49 per month, no badges |
| JSON-LD (`structured.json`) | Each plan with both prices: Start 18.00 billed monthly and 15.00 per month billed yearly, and so on | The same |
| Text (`text.txt`), fetch route | "€ 15 per maand Bespaar € 36 per jaar" and the other plans | (fetch has one state) |
| Text (`text.txt`), render route | "per maand" with **no price before it**, and the badges | The same as yearly: **no prices**, and the badges are still there |
| HTML (`page.html`), render route | "€ 15" inside `<number-flow>` | Still "€ 15" inside `<number-flow>` |

## Findings

| # | Finding | Why it matters | Where it goes |
|---|---|---|---|
| F1 | The prices are drawn by a web component (`<number-flow>`) inside its shadow root. The rendered text leaves them out, and the component's plain HTML fallback is never updated ("€ 15" in the monthly state) | Stage 2 reads prices from the text. On this page the render route would find none, or the wrong one from the HTML | Capture fix before stage 2's extraction: build the visible text from the composed tree (open shadow roots included), and serialise open shadow roots into the stored HTML. A trap page with a shadow-root price pins it |
| F2 | The "Bespaar" badges are faded out (opacity 0) in the monthly state but stay in the text | Text that is not visible must not reach extraction as if it were | The same fix: leave out elements that are not rendered visibly |
| F3 | A cookie dialog over the page blocks every click | Most European pricing pages have one; a billing toggle cannot be clicked until it is dismissed | Recipes already allow several actions per state. The add-a-brand helper (§8.4) should propose the least-consent dismissal. The CLI's `--state LABEL=TEXT` can express neither a selector nor several actions: a later stage's recipe editor covers it |
| F4 | A text click on a label next to a switch does nothing | Labels are often not the control | The helper should prefer the control (`role="switch"`, a button) over its label |

What worked as designed: robots.txt was checked and pacing held on every mihenk run; a failed
click became `action_failed` with a detail instead of a hang; every snapshot was written once,
with matching hashes; the euro sign and the page language were marked; the screenshot shows each
state truly; the JSON-LD carries both prices.
