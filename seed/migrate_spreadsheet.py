"""Seed the specialty-shows DB from the master calendar workbook.

Usage:
    python3 seed/migrate_spreadsheet.py [xlsx-path] [calendar-year]

Defaults: archive/2026-specialty-info-FB.xlsx, 2026.

Unlike the web upload this seed run creates EVERY parsed row (no duplicate
skipping — specialty clusters really do run identical-looking shows the same
day), and it writes seed/import-report.txt INCREMENTALLY, one finding per row
as it is made, so an interrupted run leaves a usable partial report and the
whole thing can be reviewed line by line afterward.

Also creates the two admin accounts (albert, patty) if missing — generated
passwords are printed ONCE to the terminal.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import db, auth, xlsx_io  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_XLSX = os.path.join(HERE, "..", "archive", "2026-specialty-info-FB.xlsx")
REPORT = os.path.join(HERE, "import-report.txt")


def main():
    xlsx = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_XLSX
    year = int(sys.argv[2]) if len(sys.argv) > 2 else 2026

    db.init()

    with open(xlsx, "rb") as f:
        rows, errors = xlsx_io.parse_upload(f.read(), year)

    existing = db.list_events(include_hidden=True) + db.list_events(status="archived", include_hidden=True)
    if existing:
        print(f"REFUSING: the database already holds {len(existing)} events. "
              f"Seed only into an empty DB (delete data/specialty.db first, or use the web upload).")
        sys.exit(1)

    created, flagged = 0, 0
    seen = {}
    with open(REPORT, "w") as rep:
        rep.write(f"Import report — {os.path.basename(xlsx)}, calendar year {year}\n")
        rep.write("Written incrementally: every parser decision, one row at a time.\n")
        rep.write("=" * 78 + "\n\n")
        rep.flush()
        for row in rows:
            notes = row.pop("_notes", [])
            src_row = row.pop("_row", "?")
            row.pop("id", None)
            key = (row["club"].lower(), row["start_date"], row["show_type"], row["judge_regular"].lower())
            if key in seen:
                notes.append(f"EXACT duplicate of sheet row {seen[key]} (same club/date/type/judge) — "
                             f"imported anyway, review whether both are real")
            seen.setdefault(key, src_row)
            eid = db.create_event(row, "seed:xlsx")
            created += 1
            line = (f"row {src_row:>4} -> event #{eid}: {row['start_date']}"
                    + (f"–{row['end_date'][5:]}" if row['end_date'] != row['start_date'] else "")
                    + f"  [{row['show_type']}]  {row['club']}")
            rep.write(line + "\n")
            for n in notes:
                rep.write(f"          NOTE: {n}\n")
                flagged += 1
            rep.flush()
        rep.write("\n" + "=" * 78 + "\n")
        rep.write(f"TOTAL: {created} shows created, {flagged} parser notes to review, "
                  f"{len(errors)} rows skipped with errors.\n")
        if errors:
            rep.write("\nSKIPPED / ERRORS:\n")
            for e in errors:
                rep.write(f"  - {e}\n")
        rep.flush()

    for uname, disp in (("albert", "Albert Collver"), ("patty", "Patty Mortara")):
        if not db.get_user(uname, include_inactive=True):
            pw = "-".join(os.urandom(2).hex() for _ in range(3))
            db.create_user(uname, disp, "admin", auth.hash_password(pw))
            print(f"created admin '{uname}' — password (shown once): {pw}")

    print(f"\n{created} shows created, {flagged} notes, {len(errors)} errors.")
    print(f"Report: {REPORT}")


if __name__ == "__main__":
    main()
