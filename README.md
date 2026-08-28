# ESSFTA Specialty Shows Calendar

A self-hosted calendar for English Springer Spaniel **conformation specialty shows**
(specialties, designated/concurrent specialties, supported entries, group shows, and the
National) — sibling app to the [ESSFTA Field Events calendar](https://essfta-events.collver.biz).

- **Public views:** month-band list, monthly calendar, printable full-year page (the
  monthly Facebook post), iCal feed, per-show detail pages — all embeddable in WordPress
  via an auto-resizing iframe (`/?embed=1`).
- **Editor backend:** password logins (editor/admin roles), add/edit forms, cancel vs hide
  vs remove, checkbox bulk actions with date shift, bulk hide/unhide with preview + one-click
  undo, roll-a-year-forward (same weekend, same weekday), full audit log.
- **Excel round-trip:** download the current calendar (with an EVENT ID column), edit in
  Excel, re-upload behind a confirm-every-change preview — **or upload the master
  "ESS Specialty & Supported Entry Calendar" workbook / Google-Sheet export as-is.**
  The parser understands its month banner rows, second-show continuation rows, shorthand
  dates ("4-Sept", "14- Oct, 15- Oct…"), and left-over years from the previous season,
  and shows every correction it made before anything is saved.
- Past shows drop off the public views automatically the day after they end — no more
  hiding spreadsheet rows month by month.

FastAPI + SQLite, single container, one volume. No JavaScript frameworks; works embedded.

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python seed/migrate_spreadsheet.py     # seed from archive/, prints admin passwords once
.venv/bin/uvicorn app.main:app --port 8792
```

Seeding writes `seed/import-report.txt` — one line per imported show plus every
normalization the parser performed. Review it.

Smoke test: `BASE=http://localhost:8792 ADMIN_USER=albert ADMIN_PW=... bash seed/smoke_test.sh`

## Deploy (NAS — mirror of essfta-events, stack 70)

1. Push to GitHub (`abc3-Mac/essfta-specialty`), build image `essfta-specialty:1.0.0` on
   the NAS, Portainer git stack on endpoint 3 with `SPECIALTY_SECRET_KEY` from
   `~/.config/essfta-specialty.env` (generate: `openssl rand -hex 32`).
2. NPM proxy host `essfta-specialty.collver.biz` → container port 8792, new LE cert.
3. Seed the volume DB (run the seed script in the container, or copy a locally seeded
   `specialty.db` in via the Docker archive API — see essfta-events HANDOFF for the recipe).
4. Reset the admin passwords at `/users` after deploy (local seed passwords don't carry).
5. Umami: create a NEW website id (do not reuse the field-events id) and add the snippet
   to `app/templates/base.html`.

## WordPress embed

The snippet (also shown live at `/embed-demo`):

```html
<iframe id="essfta-specialty" src="https://essfta-specialty.collver.biz/?embed=1"
        title="ESSFTA Specialty Shows" style="width:100%;border:0;min-height:600px"></iframe>
<script>
  window.addEventListener("message", function (e) {
    if (e.data && e.data.essftaSpecialtyHeight) {
      document.getElementById("essfta-specialty").style.height =
        (e.data.essftaSpecialtyHeight + 20) + "px";
    }
  });
</script>
```

The app sends `Content-Security-Policy: frame-ancestors` allowing
englishspringerspaniels.org and *.collver.biz.

## Layout

```
app/            FastAPI app (main.py routes, db.py SQLite layer, auth.py sessions,
                xlsx_io.py Excel parsing/building, templates/, static/)
seed/           migrate_spreadsheet.py (master-workbook import + report), smoke_test.sh
archive/        source spreadsheets (ground truth for the 2026 season)
data/           local dev DB (gitignored)
HANDOFF.md      living build log + resume instructions — read first
```
