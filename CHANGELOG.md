# Changelog

All notable changes to mihenk are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- The repository, licence (PolyForm Noncommercial 1.0.0), design and the plan for stages 0 and 1.
- A local server on 127.0.0.1 that checks Host, Origin and a one-time key on every request.
- The screens skeleton, built into the package, with API types generated from the server.
- The launcher: the window, the server thread and a release check (`--smoke`).
- Driving the installed Chrome or Edge, and a test guard that keeps every test on this machine.
- A licence allow-list check, a third-party notices file in every build, and a lint that refuses
  arithmetic on price fields.
- PyInstaller builds, the Windows installer script and the macOS disk image script.
- Continuous integration on Windows and macOS.
- Decision records 0001 to 0005.
- Trap pages for the tests: small made-up pricing pages that reproduce what breaks a capture.
- The robots.txt check before every request and redirect, and polite pacing per site.
- Fetching pages with limits on time, size and redirects, decoded the way browsers decode them.
- Page text, embedded data (JSON-LD, Next.js and Nuxt data) and locale signals: currencies and VAT
  wording in seven languages.
- Snapshot folders, written once, with a hash for every file.
- Rendering in the installed Chrome or Edge, including clicking a billing toggle.
- `mihenk capture` and `mihenk install-browser` (Chromium is downloaded only after a yes).
- Decision record 0006 and the stage 1 record.
