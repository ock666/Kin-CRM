#!/usr/bin/env bash
# Quick smoke test against a freshly-started Kin container - no Python/pytest needed,
# just curl. Run this right after `docker compose up -d --build` on a BRAND NEW instance
# (before you've clicked through the setup wizard yourself), e.g.:
#
#   ./scripts/smoke_test.sh
#   ./scripts/smoke_test.sh http://localhost:8000
#
# It creates a real admin account + a test person + a journal entry, so only run it
# against a throwaway/fresh instance, not one with real data you care about.
set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
COOKIE_JAR="$(mktemp)"
trap 'rm -f "$COOKIE_JAR"' EXIT

pass() { echo "  ✅ $1"; }
fail() { echo "  ❌ $1"; exit 1; }

echo "== 1. Health check =="
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/health")
[ "$code" = "200" ] && pass "GET /health -> 200" || fail "GET /health -> $code (expected 200)"

echo "== 2. Setup wizard (creates admin account) =="
code=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" -c "$COOKIE_JAR" "$BASE_URL/setup")
[ "$code" = "200" ] || fail "GET /setup -> $code (expected 200 - is this instance already set up?)"
pass "GET /setup -> 200"

code=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
  -d "name=Smoke Test" -d "email=smoketest@example.com" \
  -d "password=smoketestpassword123" -d "password_confirm=smoketestpassword123" \
  "$BASE_URL/setup")
[ "$code" = "303" ] && pass "POST /setup -> 303 (admin account created)" || fail "POST /setup -> $code (expected 303)"

echo "== 3. Dashboard loads while logged in =="
body=$(curl -s -b "$COOKIE_JAR" -c "$COOKIE_JAR" "$BASE_URL/")
echo "$body" | grep -qi "Today" && pass "Dashboard renders" || fail "Dashboard did not render expected content"

echo "== 4. Create a person =="
code=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
  -d "name=Smoke Test Friend" "$BASE_URL/people/new")
[ "$code" = "303" ] && pass "POST /people/new -> 303" || fail "POST /people/new -> $code (expected 303)"

body=$(curl -s -b "$COOKIE_JAR" -c "$COOKIE_JAR" "$BASE_URL/people")
echo "$body" | grep -q "Smoke Test Friend" && pass "New person appears in /people" || fail "New person missing from /people"

echo "== 5. Review queue and export pages load =="
code=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" -c "$COOKIE_JAR" "$BASE_URL/reviews")
[ "$code" = "200" ] && pass "GET /reviews -> 200" || fail "GET /reviews -> $code"

code=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" -c "$COOKIE_JAR" "$BASE_URL/export/json")
[ "$code" = "200" ] && pass "GET /export/json -> 200" || fail "GET /export/json -> $code"

echo
echo "All smoke tests passed. 🎉 Remember this created a real 'Smoke Test' admin account"
echo "and a 'Smoke Test Friend' person - delete them from Settings/People if this wasn't"
echo "a fully throwaway instance."
