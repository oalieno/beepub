#!/bin/sh
# Manage the disposable e2e stack. Wraps docker compose so the project
# name is always beepub-e2e — running the base compose file without an
# explicit project name would REPLACE a live beepub stack on the same
# docker daemon.
#
#   ./e2e/stack.sh up        # build from the working tree and start
#   ./e2e/stack.sh down      # tear down, volumes included
#   ./e2e/stack.sh <any docker compose args>
set -eu

cd "$(dirname "$0")/../.."
export PORT="${E2E_PORT:-8091}"

case "${1:-}" in
  up)
    shift
    exec docker compose -p beepub-e2e -f docker-compose.yml up -d --build "$@"
    ;;
  down)
    shift
    exec docker compose -p beepub-e2e -f docker-compose.yml down -v "$@"
    ;;
  *)
    exec docker compose -p beepub-e2e -f docker-compose.yml "$@"
    ;;
esac
