#!/bin/bash
# Smoke test for the ESSFTA Specialty Shows app.
# Usage: BASE=http://localhost:8792 ADMIN_USER=albert ADMIN_PW=... bash seed/smoke_test.sh
set -u
BASE="${BASE:-http://localhost:8792}"
JAR="$(mktemp)"
PASS=0; FAIL=0

check () {  # check <name> <expected-substring-or-code> <curl args...>
  local name="$1"; local want="$2"; shift 2
  local out
  out=$(curl -sk -b "$JAR" -c "$JAR" -w "\n%{http_code}" "$@" 2>/dev/null)
  if echo "$out" | grep -q "$want"; then
    PASS=$((PASS+1)); echo "ok   $name"
  else
    FAIL=$((FAIL+1)); echo "FAIL $name (wanted: $want)"
  fi
}

check "healthz"                '"ok":true'            "$BASE/healthz"
check "public list"            "ESSFTA Specialty Shows" "$BASE/"
check "list has type filter"   "Show type"            "$BASE/"
check "calendar"               "cal-nav"              "$BASE/calendar"
check "printable"              "Supported Entry Calendar" "$BASE/print?year=2026"
check "ics feed"               "BEGIN:VCALENDAR"      "$BASE/events.ics"
check "ics categories"         "CATEGORIES:"          "$BASE/events.ics"
check "embed list"             "embed-bar"            "$BASE/?embed=1"
check "embed demo"             "iframe"               "$BASE/embed-demo"
check "event detail"           "detail-card"          "$BASE/event/1"
check "login page"             "Editor sign-in"       "$BASE/login"
check "dashboard redirects"    "303\|login"           -o /dev/null -w "%{http_code}" "$BASE/dashboard"
check "bad login rejected"     "Wrong username"       -X POST -d "username=nobody&password=nope" "$BASE/login"

if [ -n "${ADMIN_USER:-}" ] && [ -n "${ADMIN_PW:-}" ]; then
  curl -sk -c "$JAR" -X POST -d "username=$ADMIN_USER&password=$ADMIN_PW" "$BASE/login" -o /dev/null
  check "dashboard (signed in)"  "All specialty shows"  "$BASE/dashboard"
  check "excel hub"              "Spreadsheet"          "$BASE/excel"
  check "template download"      "200"                  -o /dev/null -w "%{http_code}" "$BASE/template.xlsx"
  check "export download"        "200"                  -o /dev/null -w "%{http_code}" "$BASE/export.xlsx?year=2026"
  check "bulk page"              "Bulk hide"            "$BASE/bulk"
  check "rollforward page"       "Roll a year forward"  "$BASE/rollforward"
  check "users page"             "Editor accounts"      "$BASE/users"
  check "audit page"             "Audit log"            "$BASE/audit"
  check "help page"              "Help"                 "$BASE/help"
else
  echo "(set ADMIN_USER/ADMIN_PW to run the signed-in checks)"
fi

rm -f "$JAR"
echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
