#!/usr/bin/env bash
# Builds the image, starts the bot with .env.test, waits for /health,
# runs the smoke test inside the container, then tears everything down.
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE="docker compose -f docker-compose.test.yml"

[[ -f .env.test ]] || { echo "Missing .env.test (copy .env.test.example)"; exit 1; }
[[ -f service-account.json ]] || { echo "Missing service-account.json"; exit 1; }

cleanup() { $COMPOSE down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

$COMPOSE build
$COMPOSE run --rm --no-deps bot python tests/smoke_test.py
$COMPOSE up -d

echo "Waiting for /health ..."
for _ in $(seq 1 30); do
  if curl -fsS http://localhost:8080/health; then
    echo
    echo "Test deploy OK. Send /status to your TEST bot on Telegram."
    [[ "${KEEP_RUNNING:-0}" == "1" ]] && { trap - EXIT; echo "Left running (KEEP_RUNNING=1). Logs: $COMPOSE logs -f"; }
    exit 0
  fi
  sleep 2
done

echo "Health check failed. Recent logs:"
$COMPOSE logs --tail=50
exit 1
