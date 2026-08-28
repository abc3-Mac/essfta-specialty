"""ESSFTA Specialty Shows calendar — editor-maintained, embeddable public views.

Adapted from the ESSFTA Field Events app: same auth/audit/bulk/undo machinery,
no regions (show type is the color-coded category), conformation-show fields
(superintendent, closing date, regular + sweeps/futurity judges).
"""
import calendar as calmod
import os
from datetime import date, datetime, timedelta

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth, db, mail, xlsx_io

app = FastAPI(title="ESSFTA Specialty Shows")
HERE = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))

FRAME_ANCESTORS = os.environ.get(
    "FRAME_ANCESTORS",
    "'self' https://englishspringerspaniels.org https://*.englishspringerspaniels.org https://*.collver.biz",
)

db.init()


# ---------- helpers ----------

def fmt_dates(start: str, end: str) -> str:
    """'Sep 11' or 'Sep 12–13' or 'Sep 30 – Oct 1'."""
    s, e = date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    if s == e:
        return s.strftime("%b %-d")
    if s.month == e.month:
        return f"{s.strftime('%b %-d')}–{e.day}"
    return f"{s.strftime('%b %-d')} – {e.strftime('%b %-d')}"


def fmt_days(start: str, end: str) -> str:
    """'Friday' / 'Saturday & Sunday' / 'Thu–Sun' — derived, never typed."""
    s, e = date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    n = (e - s).days
    if n == 0:
        return s.strftime("%A")
    if n == 1:
        return f"{s.strftime('%A')} & {e.strftime('%A')}"
    return f"{s.strftime('%a')}–{e.strftime('%a')}"


def fmt_closing(iso: str) -> str:
    if not iso:
        return ""
    try:
        return date.fromisoformat(iso[:10]).strftime("%b %-d")
    except ValueError:
        return iso


templates.env.globals.update(
    fmt_dates=fmt_dates,
    fmt_days=fmt_days,
    fmt_closing=fmt_closing,
    SHOW_TYPES=db.SHOW_TYPES,
    TYPE_COLORS=db.TYPE_COLORS,
    TYPE_DEFS=db.TYPE_DEFS,
)


@app.middleware("http")
async def frame_ancestors_header(request: Request, call_next):
    # every route inherits the embed policy (incl. /login — lesson from the field app)
    resp = await call_next(request)
    resp.headers["Content-Security-Policy"] = f"frame-ancestors {FRAME_ANCESTORS}"
    return resp


def current_user(request: Request):
    sess = auth.read_session(request.cookies.get(auth.COOKIE, ""))
    if not sess:
        return None, None
    user = db.get_user(sess["u"])
    return user, sess


def signed_in(request: Request) -> bool:
    return current_user(request)[0] is not None


def past_visible(request: Request) -> bool:
    """May this viewer see past shows? Signed-in users always can; the public can
    when the admin toggle allows it (the default)."""
    return signed_in(request) or db.get_setting("public_past", "1") == "1"


def parse_filters(request: Request):
    qp = request.query_params
    return {
        "show_type": qp.get("type") or None,
        "state": qp.get("state") or None,
        "club": qp.get("club") or None,
        "include_canceled": qp.get("hide_canceled") != "1",
    }


def month_bounds(ym: str):
    y, m = int(ym[:4]), int(ym[5:7])
    last = calmod.monthrange(y, m)[1]
    return f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{last:02d}"


# ---------- public views ----------

@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def list_view(request: Request):
    f = parse_filters(request)
    qp = request.query_params
    year = qp.get("year") or str(date.today().year)
    can_past = past_visible(request)
    show_past = qp.get("past") == "1" and can_past
    events = db.list_events(
        show_type=f["show_type"], state=f["state"], club=f["club"],
        date_from=f"{year}-01-01" if show_past else max(f"{year}-01-01", date.today().isoformat()),
        date_to=f"{year}-12-31", include_canceled=f["include_canceled"],
    )
    months = {}
    for ev in events:
        key = ev["start_date"][:7]
        months.setdefault(key, []).append(ev)
    return templates.TemplateResponse(request, "list.html", {
        "months": months, "filters": f, "year": year, "show_past": show_past, "can_past": can_past,
        "states": db.distinct_states(), "years": db.distinct_event_years(), "view": "list",
        "embed": qp.get("embed") == "1",
        "month_name": lambda k: date.fromisoformat(k + "-01").strftime("%B %Y"),
    })


@app.get("/calendar", response_class=HTMLResponse)
def calendar_view(request: Request):
    f = parse_filters(request)
    can_past = past_visible(request)
    this_ym = date.today().strftime("%Y-%m")
    ym = request.query_params.get("month") or this_ym
    if not can_past and ym < this_ym:  # the public can't browse into past months
        embed_q = "&embed=1" if request.query_params.get("embed") == "1" else ""
        return RedirectResponse(f"/calendar?month={this_ym}{embed_q}", status_code=303)
    first, last = month_bounds(ym)
    if not can_past:
        first = max(first, date.today().isoformat())
    events = db.list_events(
        show_type=f["show_type"], state=f["state"], club=f["club"],
        date_from=first, date_to=last, include_canceled=f["include_canceled"],
    )
    y, m = int(ym[:4]), int(ym[5:7])
    weeks = calmod.Calendar(firstweekday=6).monthdatescalendar(y, m)  # weeks start Sunday
    by_day = {}
    for ev in events:
        s = date.fromisoformat(ev["start_date"][:10])
        e = date.fromisoformat(ev["end_date"][:10])
        d = s
        while d <= e:
            by_day.setdefault(d.isoformat(), []).append(ev)
            d += timedelta(days=1)
    prev_m = (date(y, m, 1) - timedelta(days=1)).strftime("%Y-%m")
    next_m = (date(y, m, calmod.monthrange(y, m)[1]) + timedelta(days=1)).strftime("%Y-%m")
    return templates.TemplateResponse(request, "calendar.html", {
        "weeks": weeks, "by_day": by_day, "ym": ym, "month_label": date(y, m, 1).strftime("%B %Y"),
        "prev_m": prev_m, "next_m": next_m, "this_month": m,
        "allow_prev": can_past or prev_m >= this_ym,
        "filters": f, "states": db.distinct_states(), "view": "calendar",
        "embed": request.query_params.get("embed") == "1", "today": date.today().isoformat(),
    })


@app.get("/print", response_class=HTMLResponse)
def print_view(request: Request):
    year = request.query_params.get("year") or str(date.today().year)
    date_from = f"{year}-01-01"
    if not past_visible(request):  # the public's printable page starts at today
        date_from = max(date_from, date.today().isoformat())
    events = db.list_events(date_from=date_from, date_to=f"{year}-12-31")
    months = {}
    for ev in events:
        months.setdefault(ev["start_date"][:7], []).append(ev)
    return templates.TemplateResponse(request, "print.html", {
        "months": months, "year": year,
        "month_name": lambda k: date.fromisoformat(k + "-01").strftime("%B").upper(),
    })


@app.get("/event/{event_id}", response_class=HTMLResponse)
def event_detail(request: Request, event_id: int):
    ev = db.get_event(event_id)
    if not ev or ev["status"] == "archived":
        return PlainTextResponse("Event not found", status_code=404)
    if ev.get("hidden") and not signed_in(request):
        return PlainTextResponse("Event not found", status_code=404)
    if ev["end_date"][:10] < date.today().isoformat() and not past_visible(request):
        return PlainTextResponse("Event not found", status_code=404)
    return templates.TemplateResponse(request, "event_detail.html", {
        "ev": ev, "embed": request.query_params.get("embed") == "1", "view": None,
    })


@app.get("/embed-demo", response_class=HTMLResponse)
def embed_demo(request: Request):
    """Mock WordPress page proving the iframe embed."""
    return templates.TemplateResponse(request, "embed_demo.html", {})


@app.get("/events.ics")
def ical():
    # feed readers carry no session, so the public toggle decides for everyone
    date_from = None if db.get_setting("public_past", "1") == "1" else date.today().isoformat()
    events = db.list_events(include_canceled=False, date_from=date_from)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ESSFTA//Specialty Shows//EN",
             "X-WR-CALNAME:ESSFTA Specialty Shows"]
    for ev in events:
        end = (date.fromisoformat(ev["end_date"][:10]) + timedelta(days=1)).strftime("%Y%m%d")
        summary = f"{ev['title']} ({ev['show_type']})".replace(",", r"\,")
        loc = ", ".join(x for x in (ev["city"], ev["state"]) if x).replace(",", r"\,")
        lines += [
            "BEGIN:VEVENT",
            f"UID:essfta-specialty-{ev['id']}@essfta-specialty.collver.biz",
            f"DTSTART;VALUE=DATE:{ev['start_date'][:10].replace('-', '')}",
            f"DTEND;VALUE=DATE:{end}",
            f"SUMMARY:{summary}",
            f"LOCATION:{loc}",
            f"CATEGORIES:{ev['show_type']}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return PlainTextResponse("\r\n".join(lines), media_type="text/calendar")


# ---------- auth ----------

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    ip = request.client.host if request.client else "?"
    ua = request.headers.get("user-agent", "")
    attempted = username.strip().lower()
    if auth.rate_limited(ip):
        db.log_login(attempted, "rate_limited", ip, ua)
        return templates.TemplateResponse(
            request, "login.html", {"error": "Too many attempts — wait ten minutes."}, status_code=429)
    auth.record_attempt(ip)
    user = db.get_user(attempted)
    if not user or not auth.check_password(password, user["pw_hash"]):
        db.log_login(attempted, "login_failed", ip, ua)
        return templates.TemplateResponse(
            request, "login.html", {"error": "Wrong username or password."}, status_code=401)
    db.log_login(user["username"], "login_ok", ip, ua)
    resp = RedirectResponse("/dashboard", status_code=303)
    resp.set_cookie(auth.COOKIE, auth.make_session(user["username"]),
                    httponly=True, samesite="lax", secure=True, max_age=auth.SESSION_TTL)
    return resp


@app.post("/logout")
def logout(request: Request):
    user, _ = current_user(request)
    if user:
        ip = request.client.host if request.client else "?"
        db.log_login(user["username"], "logout", ip, request.headers.get("user-agent", ""))
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(auth.COOKIE)
    return resp


# ---------- editor / admin ----------

def require_user(request: Request):
    user, sess = current_user(request)
    if not user:
        return None, None, RedirectResponse("/login", status_code=303)
    return user, sess, None


@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    return templates.TemplateResponse(request, "help.html", {"user": user})


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    events = db.list_events(include_hidden=True)
    today = date.today().isoformat()
    upcoming = [e for e in events if e["end_date"][:10] >= today]
    past = [e for e in events if e["end_date"][:10] < today][::-1]
    hidden = [e for e in events if e["hidden"]]
    archived = db.list_events(status="archived", include_hidden=True)
    return templates.TemplateResponse(request, "dashboard.html", {
        "user": user, "csrf": sess["csrf"], "upcoming": upcoming, "past": past,
        "hidden": hidden, "archived": archived[::-1],
        "public_past": db.get_setting("public_past", "1") == "1",
    })


def event_from_form(form):
    start = form.get("start_date", "")
    end = form.get("end_date", "") or start
    if end < start:
        start, end = end, start
    show_type = form.get("show_type", "Specialty")
    if show_type not in db.SHOW_TYPES:
        show_type = "Specialty"
    return {
        "title": form.get("title", "").strip(),
        "club": form.get("club", "").strip(),
        "show_type": show_type,
        "start_date": start, "end_date": end,
        "city": form.get("city", "").strip(),
        "state": form.get("state", "").strip().upper()[:2],
        "venue": form.get("venue", "").strip(),
        "closing_date": form.get("closing_date", "").strip(),
        "superintendent": form.get("superintendent", "").strip(),
        "judge_regular": form.get("judge_regular", "").strip(),
        "judge_sweeps": form.get("judge_sweeps", "").strip(),
        "link_url": form.get("link_url", "").strip(),
        "notes": form.get("notes", "").strip(),
        "status": form.get("status", "scheduled"),
    }


@app.get("/events/new", response_class=HTMLResponse)
def new_event_form(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    blank = {f: "" for f in db.EVENT_FIELDS}
    blank.update(status="scheduled", show_type="Specialty")
    return templates.TemplateResponse(request, "event_form.html", {
        "user": user, "csrf": sess["csrf"], "ev": blank, "is_new": True,
    })


@app.post("/events/new")
async def create_event(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    form = await request.form()
    if form.get("csrf") != sess["csrf"]:
        return PlainTextResponse("Bad CSRF token", status_code=403)
    data = event_from_form(form)
    if not data["title"] or not data["start_date"]:
        return PlainTextResponse("Title and start date are required", status_code=400)
    db.create_event(data, user["username"])
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/events/{event_id}/edit", response_class=HTMLResponse)
def edit_event_form(request: Request, event_id: int):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    ev = db.get_event(event_id)
    if not ev:
        return PlainTextResponse("Not found", status_code=404)
    return templates.TemplateResponse(request, "event_form.html", {
        "user": user, "csrf": sess["csrf"], "ev": ev, "is_new": False,
    })


@app.post("/events/{event_id}/edit")
async def save_event(request: Request, event_id: int):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    ev = db.get_event(event_id)
    if not ev:
        return PlainTextResponse("Not found", status_code=404)
    form = await request.form()
    if form.get("csrf") != sess["csrf"]:
        return PlainTextResponse("Bad CSRF token", status_code=403)
    db.update_event(event_id, event_from_form(form), user["username"])
    return RedirectResponse("/dashboard", status_code=303)


# ---------- spreadsheet: template, export, round-trip upload ----------

UPDATE_FIELDS = ["start_date", "end_date", "show_type", "club", "city", "state", "venue",
                 "closing_date", "superintendent", "judge_regular", "judge_sweeps"]
FIELD_LABELS = {
    "start_date": "first day", "end_date": "last day", "show_type": "show type",
    "club": "host club", "city": "city", "state": "state", "venue": "venue",
    "closing_date": "closing date", "superintendent": "superintendent",
    "judge_regular": "regular judge", "judge_sweeps": "sweeps/futurity judge",
    "title": "title",
}

# parsed-but-unconfirmed uploads, keyed by a one-time token (in-memory: this is a
# single-process app, same as the login rate limiter)
_pending_imports = {}


def _stash_import(username, payload):
    import secrets
    import time as _t
    now_t = _t.time()
    for k in [k for k, v in _pending_imports.items() if v["exp"] < now_t]:
        _pending_imports.pop(k, None)
    tok = secrets.token_hex(8)
    _pending_imports[tok] = {"u": username, "exp": now_t + 900, **payload}
    return tok


def _same_show_on_calendar(row):
    """A row duplicates an existing event only if club + date + show type match AND
    the regular judge matches — specialty clusters really do run two shows of the
    same type for the same club on one day, told apart by their judges."""
    dup = db.find_near_duplicate(row["club"], row["start_date"], days=0,
                                 show_type=row.get("show_type"))
    if not dup:
        return None
    ev = db.get_event(dup["id"])
    if ev and (ev["judge_regular"] or "") == (row.get("judge_regular") or ""):
        return dup
    return None


@app.get("/excel", response_class=HTMLResponse)
def excel_page(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    return templates.TemplateResponse(request, "excel.html", {
        "user": user, "csrf": sess["csrf"], "years": db.distinct_event_years(),
        "this_year": date.today().year,
    })


@app.get("/export.xlsx")
def export_download(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    try:
        year = int(request.query_params.get("year", date.today().year))
    except ValueError:
        return PlainTextResponse("Bad year", status_code=400)
    events = db.bulk_select(f"{year}-01-01", f"{year}-12-31",
                            ("scheduled", "canceled", "postponed"))
    fname = f"ESSFTA-specialty-shows-{year}.xlsx"
    return Response(
        xlsx_io.build_export(events, year),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.get("/template.xlsx")
def template_download(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    return Response(
        xlsx_io.build_template(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="ESSFTA-specialty-shows-template.xlsx"'},
    )


@app.post("/import")
async def import_xlsx(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    form = await request.form()
    if form.get("csrf") != sess["csrf"]:
        return PlainTextResponse("Bad CSRF token", status_code=403)
    upload = form.get("file")
    if upload is None or not getattr(upload, "filename", ""):
        return PlainTextResponse("No file uploaded", status_code=400)
    try:
        calendar_year = int(form.get("calendar_year", date.today().year))
    except ValueError:
        calendar_year = date.today().year
    try:
        rows, errors = xlsx_io.parse_upload(await upload.read(), calendar_year)
    except Exception:
        return templates.TemplateResponse(request, "import_result.html", {
            "user": user, "created": [], "updated": [], "skipped": [],
            "errors": ["That file could not be read as an Excel (.xlsx) spreadsheet."],
        })
    if form.get("as_new") == "1":
        # "treat every row as new" — the make-next-year-from-this-year's-export workflow
        for row in rows:
            row["id"] = None

    id_rows = [r for r in rows if r.get("id")]
    new_rows = [r for r in rows if not r.get("id")]

    # every upload gets a confirm-first preview (the master workbook is messy enough
    # that even a plain create run deserves a look before it lands)
    updates, unchanged = [], 0
    for row in id_rows:
        ev = db.get_event(row["id"])
        if not ev or ev["status"] == "archived":
            errors.append(f"Row for '{row['club']}': no event #{row['id']} on the calendar — skipped")
            continue
        changes = {}
        for f in UPDATE_FIELDS:
            if str(row.get(f, "")) != str(ev[f] if ev[f] is not None else ""):
                changes[f] = row[f]
        if "club" in changes and ev["title"] == ev["club"]:
            changes["title"] = changes["club"]  # derived titles follow the club name
        if changes:
            updates.append({"id": ev["id"], "label": ev["club"] or ev["title"],
                            "old": {f: ev[f] for f in changes}, "changes": changes})
        else:
            unchanged += 1
    creates = []
    for row in new_rows:
        row.pop("id", None)
        creates.append({"row": row, "dup": _same_show_on_calendar(row),
                        "notes": row.get("_notes", [])})
    token = _stash_import(user["username"], {
        "updates": [(u["id"], u["changes"]) for u in updates],
        "creates": [c["row"] for c in creates if not c["dup"]],
        "errors": errors,
    })
    return templates.TemplateResponse(request, "import_preview.html", {
        "user": user, "csrf": sess["csrf"], "token": token,
        "updates": updates, "creates": creates, "unchanged": unchanged,
        "errors": errors, "labels": FIELD_LABELS,
    })


@app.post("/import/apply")
async def import_apply(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    form = await request.form()
    if form.get("csrf") != sess["csrf"]:
        return PlainTextResponse("Bad CSRF token", status_code=403)
    pending = _pending_imports.pop(form.get("pending", ""), None)
    import time as _t
    if not pending or pending["u"] != user["username"] or pending["exp"] < _t.time():
        return PlainTextResponse("This upload preview expired — please upload the file again.",
                                 status_code=410)
    batch = new_batch_id()
    updated, created, skipped, errors = [], [], [], list(pending["errors"])
    for event_id, changes in pending["updates"]:
        ev = db.get_event(event_id)
        if not ev:  # re-checked at apply time, not just preview
            errors.append(f"Event #{event_id} could not be updated — skipped")
            continue
        db.update_event(event_id, changes, user["username"] + ":xlsx", batch_id=batch, action="xlsx-update")
        updated.append({"id": event_id, "label": ev["club"] or ev["title"], "changes": changes})
    for row in pending["creates"]:
        if _same_show_on_calendar(row):
            skipped.append(f"{row['club']} — {row['start_date']} already on the calendar")
            continue
        eid = db.create_event(row, user["username"] + ":xlsx", batch_id=batch)
        created.append({**row, "id": eid})
    if updated or created:
        db.create_batch(batch, user["username"], "xlsx-import",
                        f"spreadsheet: {len(updated)} updated, {len(created)} added", len(updated) + len(created))
    else:
        batch = None
    return templates.TemplateResponse(request, "import_result.html", {
        "user": user, "created": created, "updated": updated, "skipped": skipped,
        "errors": errors, "batch_id": batch, "csrf": sess["csrf"],
    })


# ---------- admin: manage editor accounts ----------

def require_admin(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return None, None, redir
    if user["role"] != "admin":
        return None, None, PlainTextResponse("Admins only", status_code=403)
    return user, sess, None


def generate_password():
    import secrets
    return "-".join(secrets.token_hex(2) for _ in range(3))


def render_users(request, user, sess, new_password=None, pw_for=None, mail_note=None):
    return templates.TemplateResponse(request, "users.html", {
        "user": user, "csrf": sess["csrf"], "users": db.list_users(),
        "last_seen": db.last_seen_map(),
        "new_password": new_password, "pw_for": pw_for,
        "mail_note": mail_note, "mail_on": mail.configured(),
    })


@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    user, sess, redir = require_admin(request)
    if redir:
        return redir
    return render_users(request, user, sess)


@app.post("/settings")
def save_settings(request: Request, public_past: str = Form("0"), csrf: str = Form(...)):
    user, sess, redir = require_admin(request)
    if redir:
        return redir
    if csrf != sess["csrf"] or public_past not in ("0", "1"):
        return PlainTextResponse("Bad request", status_code=403)
    db.set_setting("public_past", public_past, user["username"])
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/settings/colors")
async def save_type_colors(request: Request):
    user, sess, redir = require_admin(request)
    if redir:
        return redir
    form = await request.form()
    if form.get("csrf") != sess["csrf"]:
        return PlainTextResponse("Bad CSRF token", status_code=403)
    if form.get("do") == "default":
        db.set_type_colors(None, user["username"])
        return RedirectResponse("/dashboard", status_code=303)
    colors = {}
    for i, t in enumerate(db.SHOW_TYPES):
        v = (form.get(f"color_{i}") or "").strip().lower()
        if len(v) != 7 or v[0] != "#" or not all(c in "0123456789abcdef" for c in v[1:]):
            return PlainTextResponse(f"Bad color for {t}", status_code=400)
        colors[t] = v
    db.set_type_colors(colors, user["username"])
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request):
    """Admin-only: who signed in (or tried to), and who changed what. IPs are personal
    data — this page must never be linked from a public view or embedded."""
    user, sess, redir = require_admin(request)
    if redir:
        return redir
    qp = request.query_params
    f_user = qp.get("user") or None
    f_from = qp.get("from") or None
    f_to = qp.get("to") or None
    return templates.TemplateResponse(request, "audit.html", {
        "user": user, "csrf": sess["csrf"],
        "logins": db.list_login_events(username=f_user, date_from=f_from, date_to=f_to),
        "changes": db.recent_event_changes(150),
        "usernames": [u["username"] for u in db.list_users()],
        "f_user": f_user, "f_from": f_from, "f_to": f_to,
    })


@app.post("/users/new")
def add_editor(request: Request, username: str = Form(...), display_name: str = Form(...),
               role: str = Form("editor"), email: str = Form(""), csrf: str = Form(...)):
    user, sess, redir = require_admin(request)
    if redir:
        return redir
    if csrf != sess["csrf"] or role not in ("editor", "admin"):
        return PlainTextResponse("Bad request", status_code=403)
    username = username.strip().lower()
    if not username.isalnum() or db.get_user(username, include_inactive=True):
        return PlainTextResponse("Username taken or invalid (letters/numbers only)", status_code=400)
    email = email.strip()
    if email and ("@" not in email or " " in email):
        return PlainTextResponse("That email address doesn't look right", status_code=400)
    pw = generate_password()
    db.create_user(username, display_name.strip(), role, auth.hash_password(pw), email=email)
    mail_note = None
    if email:
        err = mail.send_invite(email, display_name.strip(), username, pw)
        mail_note = (f"Sign-in details emailed to {email}." if err is None else
                     f"Could not email {email} ({err}) — hand the password over yourself.")
    return render_users(request, user, sess, new_password=pw, pw_for=username, mail_note=mail_note)


@app.post("/users/{username}/resetpw")
def reset_password(request: Request, username: str, csrf: str = Form(...)):
    user, sess, redir = require_admin(request)
    if redir:
        return redir
    target = db.get_user(username, include_inactive=True)
    if csrf != sess["csrf"] or not target:
        return PlainTextResponse("Bad request", status_code=403)
    pw = generate_password()
    db.set_password(username, auth.hash_password(pw))
    mail_note = None
    if target.get("email"):
        err = mail.send_invite(target["email"], target["display_name"], username, pw, is_reset=True)
        mail_note = (f"New password emailed to {target['email']}." if err is None else
                     f"Could not email {target['email']} ({err}) — hand the password over yourself.")
    return render_users(request, user, sess, new_password=pw, pw_for=username, mail_note=mail_note)


@app.post("/users/{username}/active")
def toggle_active(request: Request, username: str, active: str = Form(...), csrf: str = Form(...)):
    user, sess, redir = require_admin(request)
    if redir:
        return redir
    target = db.get_user(username, include_inactive=True)
    if csrf != sess["csrf"] or not target:
        return PlainTextResponse("Bad request", status_code=403)
    if target["username"] == user["username"]:
        return PlainTextResponse("You can't deactivate your own account", status_code=400)
    db.set_user_active(username, active == "1")
    return RedirectResponse("/users", status_code=303)


@app.post("/events/{event_id}/status")
async def change_status(request: Request, event_id: int, status: str = Form(...), csrf: str = Form(...)):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    ev = db.get_event(event_id)
    if not ev:
        return PlainTextResponse("Not found", status_code=404)
    if csrf != sess["csrf"] or status not in ("scheduled", "canceled", "postponed", "archived"):
        return PlainTextResponse("Bad request", status_code=403)
    if status == "archived" and user["role"] != "admin":
        return PlainTextResponse("Admins only", status_code=403)
    db.set_status(event_id, status, user["username"])
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/events/{event_id}/hidden")
async def change_hidden(request: Request, event_id: int, hidden: str = Form(...), csrf: str = Form(...)):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    ev = db.get_event(event_id)
    if not ev:
        return PlainTextResponse("Not found", status_code=404)
    if csrf != sess["csrf"] or hidden not in ("0", "1"):
        return PlainTextResponse("Bad request", status_code=403)
    db.set_hidden(event_id, hidden == "1", user["username"])
    return RedirectResponse("/dashboard", status_code=303)


# ---------- bulk operations (hide / unhide by date range, batch undo) ----------

BULK_ACTIONS = {
    # action -> (label, select kwargs for bulk_select, apply function, admin_only)
    "hide": ("Hide from all public views",
             {"statuses": ("scheduled", "canceled", "postponed"), "hidden": 0},
             lambda eid, u, b: db.set_hidden(eid, True, u, batch_id=b), False),
    "unhide": ("Put back on the public views",
               {"statuses": ("scheduled", "canceled", "postponed"), "hidden": 1},
               lambda eid, u, b: db.set_hidden(eid, False, u, batch_id=b), False),
    "remove": ("Remove (move to the removed list)",
               {"statuses": ("scheduled", "canceled", "postponed")},
               lambda eid, u, b: db.set_status(eid, "archived", u, batch_id=b), True),
    "restore": ("Restore removed shows to the calendar",
                {"statuses": ("archived",)},
                lambda eid, u, b: db.set_status(eid, "scheduled", u, batch_id=b), True),
}


def _iso(s):
    try:
        return date.fromisoformat((s or "").strip()).isoformat()
    except ValueError:
        return None


def new_batch_id():
    import secrets
    return date.today().strftime("%y%m%d") + "-" + secrets.token_hex(3)


def render_bulk(request, user, sess, **extra):
    batches = db.list_batches(created_by=None if user["role"] == "admin" else user["username"])
    ctx = {"user": user, "csrf": sess["csrf"], "stage": "form",
           "today": date.today().isoformat(), "batches": batches,
           "message": None, "error": None}
    ctx.update(extra)
    return templates.TemplateResponse(request, "bulk.html", ctx)


@app.get("/bulk", response_class=HTMLResponse)
def bulk_form(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    return render_bulk(request, user, sess)


async def bulk_params(request, user, sess):
    """Shared validation for preview and apply. Returns (params, error_response)."""
    form = await request.form()
    if form.get("csrf") != sess["csrf"]:
        return None, PlainTextResponse("Bad CSRF token", status_code=403)
    action = form.get("action", "")
    if action not in BULK_ACTIONS:
        return None, PlainTextResponse("Bad request", status_code=400)
    if BULK_ACTIONS[action][3] and user["role"] != "admin":
        return None, PlainTextResponse("Admins only", status_code=403)
    date_from, date_to = _iso(form.get("date_from")), _iso(form.get("date_to"))
    if not date_from or not date_to or date_to < date_from:
        return None, render_bulk(request, user, sess, error="Please give a valid date range (from ≤ to).")
    return {"action": action, "date_from": date_from, "date_to": date_to}, None


@app.post("/bulk/preview")
async def bulk_preview(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    p, err = await bulk_params(request, user, sess)
    if err:
        return err
    label, sel, _, _ = BULK_ACTIONS[p["action"]]
    events = db.bulk_select(p["date_from"], p["date_to"], **sel)
    return render_bulk(request, user, sess, stage="preview", events=events,
                       action=p["action"], action_label=label,
                       date_from=p["date_from"], date_to=p["date_to"])


@app.post("/bulk/apply")
async def bulk_apply(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    p, err = await bulk_params(request, user, sess)
    if err:
        return err
    label, sel, apply_fn, _ = BULK_ACTIONS[p["action"]]
    # re-select server-side: what gets changed is exactly what the preview showed,
    # never a list of ids the browser could have tampered with
    events = db.bulk_select(p["date_from"], p["date_to"], **sel)
    if not events:
        return render_bulk(request, user, sess, error="Nothing matched — no shows were changed.")
    batch = new_batch_id()
    for ev in events:
        apply_fn(ev["id"], user["username"], batch)
    desc = f"{p['action']}: {p['date_from']} → {p['date_to']}"
    db.create_batch(batch, user["username"], p["action"], desc, len(events))
    return render_bulk(request, user, sess, stage="result", events=events,
                       action_label=label, batch_id=batch,
                       message=f"Done — {len(events)} show{'s' if len(events) != 1 else ''} changed "
                               f"(batch {batch}). You can undo this below.")


@app.post("/bulk/undo")
async def bulk_undo(request: Request, batch_id: str = Form(...), csrf: str = Form(...)):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    if csrf != sess["csrf"]:
        return PlainTextResponse("Bad CSRF token", status_code=403)
    batch = db.get_batch(batch_id)
    if not batch:
        return PlainTextResponse("No such batch", status_code=404)
    if user["role"] != "admin" and batch["created_by"] != user["username"]:
        return PlainTextResponse("Not your batch to undo", status_code=403)
    if batch["undone_at"]:
        return render_bulk(request, user, sess, error=f"Batch {batch_id} was already undone.")
    import json as _json
    count = 0
    for h in db.batch_history(batch_id):
        snap = _json.loads(h["snapshot_json"]) or {}
        if h["action"] == "create":
            # a roll-forward/copy/import created this event: archive it (nothing is ever hard-deleted)
            db.set_status(h["event_id"], "archived", user["username"], batch_id=batch_id + "-undo")
        else:
            # snapshots are taken BEFORE a change, so restoring one restores dates,
            # status, and hidden flag alike — works for hide, shift, and xlsx edits
            db.restore_snapshot(h["event_id"], snap, user["username"], batch_id=batch_id + "-undo")
        count += 1
    db.mark_batch_undone(batch_id)
    return render_bulk(request, user, sess,
                       message=f"Batch {batch_id} undone — {count} show{'s' if count != 1 else ''} put back.")


@app.post("/bulk/selected")
async def bulk_selected(request: Request):
    """The ticked-checkboxes action bar on the dashboard."""
    user, sess, redir = require_user(request)
    if redir:
        return redir
    form = await request.form()
    if form.get("csrf") != sess["csrf"]:
        return PlainTextResponse("Bad CSRF token", status_code=403)
    action = form.get("action", "")
    if action not in ("hide", "unhide", "cancel", "reinstate", "remove", "restore", "shift"):
        return PlainTextResponse("Bad request", status_code=400)
    if action in ("remove", "restore") and user["role"] != "admin":
        return PlainTextResponse("Admins only", status_code=403)
    days = 0
    if action == "shift":
        try:
            days = int(form.get("days", ""))
        except ValueError:
            days = 0
        if days == 0 or abs(days) > 370:
            return render_bulk(request, user, sess,
                               error="Shift needs a number of days between -370 and 370 (7 = one week later, -7 = one week earlier).")
    ids = []
    for raw in form.getlist("ids"):
        try:
            ids.append(int(raw))
        except ValueError:
            pass
    if not ids:
        return render_bulk(request, user, sess, error="No shows were ticked — nothing to do.")
    batch = new_batch_id()
    done, skipped = 0, 0
    for eid in ids:
        ev = db.get_event(eid)
        if not ev:
            skipped += 1
            continue
        if action == "hide" and not ev["hidden"]:
            db.set_hidden(eid, True, user["username"], batch_id=batch)
        elif action == "unhide" and ev["hidden"]:
            db.set_hidden(eid, False, user["username"], batch_id=batch)
        elif action == "cancel" and ev["status"] == "scheduled":
            db.set_status(eid, "canceled", user["username"], batch_id=batch)
        elif action == "reinstate" and ev["status"] in ("canceled", "postponed"):
            db.set_status(eid, "scheduled", user["username"], batch_id=batch)
        elif action == "remove" and ev["status"] != "archived":
            db.set_status(eid, "archived", user["username"], batch_id=batch)
        elif action == "restore" and ev["status"] == "archived":
            db.set_status(eid, "scheduled", user["username"], batch_id=batch)
        elif action == "shift":
            s = date.fromisoformat(ev["start_date"][:10]) + timedelta(days=days)
            e = date.fromisoformat(ev["end_date"][:10]) + timedelta(days=days)
            db.update_event(eid, {"start_date": s.isoformat(), "end_date": e.isoformat()},
                            user["username"], batch_id=batch, action="shift")
        else:
            skipped += 1  # ticked, but the action doesn't apply to its state
            continue
        done += 1
    if not done:
        return render_bulk(request, user, sess,
                           error="None of the ticked shows could take that action — nothing changed.")
    label = {"hide": "hidden", "unhide": "unhidden", "cancel": "canceled", "reinstate": "reinstated",
             "remove": "removed", "restore": "restored",
             "shift": f"shifted {days:+d} day{'s' if abs(days) != 1 else ''}"}[action]
    db.create_batch(batch, user["username"], action, f"ticked shows {label}", done)
    msg = f"Done — {done} show{'s' if done != 1 else ''} {label} (batch {batch}). You can undo this below."
    if skipped:
        msg += f" {skipped} ticked show{'s were' if skipped != 1 else ' was'} skipped (not applicable)."
    return render_bulk(request, user, sess, message=msg)


@app.post("/events/{event_id}/copyforward")
async def copy_forward(request: Request, event_id: int, csrf: str = Form(...)):
    """One-row 'Copy to next year': same carry/shift rules as the season roll-forward."""
    user, sess, redir = require_user(request)
    if redir:
        return redir
    ev = db.get_event(event_id)
    if not ev:
        return PlainTextResponse("Not found", status_code=404)
    if csrf != sess["csrf"]:
        return PlainTextResponse("Bad CSRF token", status_code=403)
    s = date.fromisoformat(ev["start_date"][:10])
    e = date.fromisoformat(ev["end_date"][:10])
    ty = s.year + 1
    ns = shift_to_year(s, ty)
    ne = ns + (e - s)
    dup = db.find_near_duplicate(ev["club"], ns.isoformat(), show_type=ev["show_type"])
    if dup:
        return render_bulk(request, user, sess,
                           error=f"Not copied — {ev['club'] or ev['title']} already has a show near "
                                 f"{ns.strftime('%b %-d, %Y')} (starting {dup['start_date']}).")
    data = {f: ev[f] for f in ROLL_CARRY}
    data["title"] = (ev["title"] or "").replace(str(s.year), str(ty))
    data["start_date"], data["end_date"] = ns.isoformat(), ne.isoformat()
    data["status"] = "scheduled"
    data["source"] = "rollforward"
    batch = new_batch_id()
    eid = db.create_event(data, user["username"], batch_id=batch)
    db.create_batch(batch, user["username"], "copy",
                    f"copy to {ty}: {data['club'] or data['title']}", 1)
    return RedirectResponse(f"/events/{eid}/edit", status_code=303)


# ---------- roll a season forward ----------

ROLL_CARRY = ["club", "show_type", "city", "state", "venue", "superintendent"]
# judges, closing dates, links and notes change every year — deliberately NOT carried


def shift_to_year(d: date, target_year: int) -> date:
    """Same time of year, same day of the week: nearest matching weekday to the
    anniversary date. For a one-year roll this is the familiar 52/53-week shift."""
    try:
        anchor = d.replace(year=target_year)
    except ValueError:  # Feb 29
        anchor = d.replace(year=target_year, day=28)
    delta = (d.weekday() - anchor.weekday()) % 7
    cand = anchor + timedelta(days=delta)
    return cand - timedelta(days=7) if delta > 3 else cand


def build_roll_plan(source_year: int, target_year: int):
    """Plan rows: (source event, new_start, new_end, disposition, dup_of)."""
    events = db.bulk_select(f"{source_year}-01-01", f"{source_year}-12-31",
                            ("scheduled", "canceled", "postponed"))
    plan = []
    for ev in events:
        s = date.fromisoformat(ev["start_date"][:10])
        e = date.fromisoformat(ev["end_date"][:10])
        ns = shift_to_year(s, target_year)
        ne = ns + (e - s)
        if ev["status"] == "canceled":
            plan.append({"ev": ev, "new_start": ns.isoformat(), "new_end": ne.isoformat(),
                         "disposition": "canceled", "dup_of": None})
            continue
        dup = db.find_near_duplicate(ev["club"], ns.isoformat(), show_type=ev["show_type"])
        plan.append({"ev": ev, "new_start": ns.isoformat(), "new_end": ne.isoformat(),
                     "disposition": "dup" if dup else "create", "dup_of": dup})
    return plan


def render_roll(request, user, sess, **extra):
    years = db.distinct_event_years()
    this_year = date.today().year
    ctx = {"user": user, "csrf": sess["csrf"], "stage": "form", "years": years,
           "source_year": this_year, "target_year": this_year + 1,
           "message": None, "error": None}
    ctx.update(extra)
    return templates.TemplateResponse(request, "rollforward.html", ctx)


@app.get("/rollforward", response_class=HTMLResponse)
def rollforward_form(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    return render_roll(request, user, sess)


async def roll_params(request, user, sess):
    form = await request.form()
    if form.get("csrf") != sess["csrf"]:
        return None, None, PlainTextResponse("Bad CSRF token", status_code=403)
    try:
        sy, ty = int(form.get("source_year", "")), int(form.get("target_year", ""))
    except ValueError:
        return None, None, PlainTextResponse("Bad year", status_code=400)
    if not (2000 <= sy <= 2100 and 2000 <= ty <= 2100) or sy == ty:
        return None, None, render_roll(request, user, sess,
                                       error="Pick a source year and a different target year.")
    return form, {"sy": sy, "ty": ty}, None


@app.post("/rollforward/preview")
async def rollforward_preview(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    form, p, err = await roll_params(request, user, sess)
    if err:
        return err
    plan = build_roll_plan(p["sy"], p["ty"])
    return render_roll(request, user, sess, stage="preview", plan=plan,
                       source_year=p["sy"], target_year=p["ty"],
                       creatable=sum(1 for r in plan if r["disposition"] == "create"))


@app.post("/rollforward/apply")
async def rollforward_apply(request: Request):
    user, sess, redir = require_user(request)
    if redir:
        return redir
    form, p, err = await roll_params(request, user, sess)
    if err:
        return err
    include = set(form.getlist("include"))
    # the plan is recomputed server-side; the checkboxes can only NARROW it
    plan = [r for r in build_roll_plan(p["sy"], p["ty"])
            if r["disposition"] == "create" and str(r["ev"]["id"]) in include]
    if not plan:
        return render_roll(request, user, sess, error="Nothing selected — no shows were created.")
    batch = new_batch_id()
    created = []
    for r in plan:
        ev = r["ev"]
        data = {f: ev[f] for f in ROLL_CARRY}
        data["title"] = (ev["title"] or "").replace(str(p["sy"]), str(p["ty"]))
        data["start_date"], data["end_date"] = r["new_start"], r["new_end"]
        data["status"] = "scheduled"
        data["source"] = "rollforward"
        eid = db.create_event(data, user["username"], batch_id=batch)
        created.append({**data, "id": eid})
    db.create_batch(batch, user["username"], "rollforward",
                    f"rollforward: {p['sy']} → {p['ty']}", len(created))
    return render_roll(request, user, sess, stage="result", created=created,
                       source_year=p["sy"], target_year=p["ty"], batch_id=batch,
                       message=f"Created {len(created)} show{'s' if len(created) != 1 else ''} "
                               f"for {p['ty']} (batch {batch}).")
