# ESSFTA Specialty Shows — HANDOFF (living build log)

**Read this first in any new session.** This file is updated AS THE BUILD PROGRESSES so
an interrupted session can resume without re-deriving anything.

## What this is
A conformation **specialty-show calendar** for ESSFTA — sibling app to the Field Events
calendar (`~/Documents/essfta-events`, LIVE at essfta-events.collver.biz). Same design:
FastAPI + SQLite, editor/admin logins, public embeddable views for a WordPress iframe on
englishspringerspaniels.org. Target domain: **essfta-specialty.collver.biz**, port **8792**
(field events uses 8791). Albert confirmed 28 Aug 2026: "designed like the essfta field
trial with a back end et al and then the embeddable part in WordPress."

## Key design decisions (settled — do not re-litigate)
- **No regions.** Conformation shows have no regional governors. The color-coded category
  is **SHOW TYPE**: National Specialty / Specialty / Designated Specialty / Concurrent
  Specialty / Supported Entry / Group Show. Colors admin-adjustable (settings key
  `type_colors`), defaults in `app/db.py` (National = brand maroon #681e12).
- **Roles:** `editor` (any show may be edited — no region locking) + `admin`. Otherwise the
  auth/users/audit machinery is carried over intact.
- **Event fields:** title, club (host club), show_type, start/end_date, city, state, venue,
  closing_date, superintendent, judge_regular, judge_sweeps (sweepstakes/futurity),
  link_url, notes, status, hidden. No stakes checkboxes, no cost.
- **The killer feature:** the xlsx upload understands the REAL master workbook Patty's side
  maintains ("ESS Specialty & Supported Entry Calendar" — MONTH/DATES … SWEEPSTAKES/FUTURITY
  JUDGE), not just our clean template. `app/xlsx_io.py::parse_master` handles its quirks:
  - month banner rows (JANUARY…) + next-year markers (`2027-01-01` cells / "March 2027")
  - **typed YEARS are unreliable** (rolled-forward file) — month/day trusted, year from section
  - blank cells inherit downward (location/closing/superintendent written once per cluster;
    a dateless row = second show the same day)
  - string dates `4-Sept`, `1-Nov.`, `14- Oct, 15- Oct, 16- Oct, 17- Oct` (= range)
  - every normalization recorded in per-row `_notes` for human review
- Seed data: `archive/2026-specialty-shows-TEST.xlsx` (Albert's TEST copy, 139 data rows,
  2026 calendar + early-2027 preview tail) and `archive/2026-specialty-info-FB.xlsx`
  (the real thing, 153 non-blank rows — same format, parser confirmed against both).
  **Workflow context (Patty, 28 Aug 2026):** the master lives as a GOOGLE SHEET in this
  exact format; "as the months go by we just hide the upper rows"; it used to be an Excel
  uploaded to Facebook once a month. This app replaces the row-hiding by dropping past
  shows automatically, and /print can serve the monthly FB post. Seed from the FB file
  (it's the current one), keep the TEST copy for parser regression.
- Dropped vs field events: `/grid` view (was date×region). Kept: list, calendar, print,
  ics, detail, embed, dashboard, bulk, rollforward, excel round-trip, users, audit, help.

## BUILD CHECKLIST — state as of last update
- [x] Project scaffold `~/Documents/essfta-specialty/` (+ style.css, logo copied from field events)
- [x] `app/db.py` — schema, show types, type_colors, batches/history/audit (adapted, regionless)
- [x] `app/auth.py` — cookie `essfta_specialty_session`, env `SPECIALTY_SECRET_KEY`
- [x] `app/xlsx_io.py` — master-format + template parsers, build_template/build_export
- [x] `app/main.py` — routes (adapt from field events; drop grid/regions; excel upload takes a
      calendar-year field for master-format files)
- [x] templates: base, list, calendar, print, event_detail, event_form, dashboard, login,
      users, audit, excel, import_preview, import_result, bulk, rollforward, help, embed_demo
- [x] `seed/migrate_spreadsheet.py` — import archive xlsx via parse_master, WRITE REPORT AS IT
      GOES to `seed/import-report.txt` (year fixes, inheritances, flags), create admin users
      albert + patty (generated pw shown once in terminal)
- [x] run locally (uvicorn, port 8792), browser-verify list/calendar/embed/dashboard
- [x] `seed/smoke_test.sh` — 22/22 passing (adapt from field events)
- [x] Dockerfile / docker-compose.yml / requirements.txt / README.md (deploy steps for NAS:
      Portainer stack, NPM host essfta-specialty.collver.biz + LE cert, secret in
      `~/.config/essfta-specialty.env` — mirror the essfta-events recipe in its HANDOFF)
- [x] memory file `project-essfta-specialty.md` + show Albert

**DEPLOYED TO NAS 28 Aug 2026 (evening):** GitHub `abc3-Mac/essfta-specialty` (public),
Portainer git stack **82** (endpoint 3, image `essfta-specialty:1.0.0` NAS-built), secret +
Mailgun SMTP env in the stack AND `~/.config/essfta-specialty.env` (600). Seeded DB pushed
into the volume via Docker archive API (⚠️ build the tar with Python tarfile — macOS bsdtar
embeds com.apple.provenance xattrs the NAS filesystem rejects with lsetxattr 500). Verified
over Tailscale :8792 — healthz ok, 124 shows, albert login 303 (passwords carried with the
DB). ⚠️ Compose gotcha: stack env vars only interpolate — every var the APP needs must also
be listed under the service's `environment:` (SMTP vars were missing on first redeploy).
**Editor email invites SHIPPED** (app/mail.py, Mailgun SMTP, optional email on /users
create; resets email automatically when an address is on file; UI wording adapts when
unconfigured). **FULLY LIVE 28 Aug 2026 (late evening): https://essfta-specialty.collver.biz** —
Albert ran npm_host.py himself (LE cert **54**, proxy host **41**); https smoke test
22/22 against the live domain; mail-enabled wording confirmed on live /users.
Still to do: Albert sends a real test invite via /users (feature untested end-to-end);
WP embed page + Umami new site id + landing-page card (show wording first). Also found + spawned task:
live essfta-events stack 70 runs with EMPTY EVENTS_SECRET_KEY (dev-fallback secret,
forgeable sessions) — Albert started that fix task separately.

**BUILD COMPLETE 28 Aug 2026 — v0 verified locally.** Seeded from the FB workbook:
136 shows (124×2026 + 12×2027 preview), 0 errors, 249 review notes in
seed/import-report.txt. Smoke test 22/22. Admin passwords printed once in-session
(albert/patty — Albert has them; reset at /users if lost, or delete data/specialty.db
and reseed). NEXT: Albert reviews import-report.txt + the app, then git init/GitHub,
NAS deploy, WordPress page — all pending his go.

## Resume instructions
1. `cat` this checklist; the first unticked box is the next task.
2. Reference implementation for anything unclear: `~/Documents/essfta-events/` (main.py
   route structure, templates, smoke test, deploy notes in its HANDOFF.md/README.md).
3. Templates are near-copies of the field-events ones with: REGIONS→(gone),
   EVENT_TYPES→SHOW_TYPES, REGION_COLORS→TYPE_COLORS keyed on `ev.show_type`, stakes
   columns→judges/superintendent/closing columns, "governor"→"editor" wording.
4. Run locally: `cd ~/Documents/essfta-specialty && python3 -m uvicorn app.main:app --port 8792`
   (deps: fastapi uvicorn jinja2 python-multipart bcrypt openpyxl — same as essfta-events).
5. NOT yet done anywhere: git repo, GitHub, NAS deploy, WordPress page, Umami site-id
   (needs a NEW id — do NOT reuse field events' 7db0c4bd). Ask Albert before publishing
   anything public (standing rule).

## Open questions for Albert (non-blocking)
- Who besides albert/patty gets editor accounts (show chairs?).
- "Group Show & Supported Entry" rows: currently recorded as Supported Entry with a note.
- Aloha State Jan 24 continuation row: parser assumes same-day second show; sheet may mean
  next-day — review in import report.
