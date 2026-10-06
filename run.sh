#!/usr/bin/env bash
# One command per job. `up` starts everything in dependency order and checks each before the next:
#   Postgres -> Toolbox -> Judge -> Masker -> Phoenix -> (web). Phoenix keeps running when the CLI exits (O-1).
set -uo pipefail
cd "$(dirname "$0")"
[ -f .env ] && { set -a; source .env; set +a; }
C=cs-postgres
TOOLBOX_PORT="${TOOLBOX_PORT:-5700}"   # not 5000: macOS AirPlay owns it
PY=.venv/bin/python
mkdir -p .run logs .phoenix

wait_for() {   # wait_for <name> <url> [seconds]
  for _ in $(seq 1 "${3:-40}"); do curl -fs -m 2 "$2" >/dev/null 2>&1 && { echo "  ok    $1"; return 0; }; sleep 1; done
  echo "  FAIL  $1 ($2)"; return 1
}
start() {   # start <name> <command...>   (background, pid + log under .run/ and logs/)
  local name=$1; shift
  if [ -f ".run/$name.pid" ] && kill -0 "$(cat ".run/$name.pid")" 2>/dev/null; then return 0; fi
  nohup "$@" >"logs/$name.log" 2>&1 & echo $! >".run/$name.pid"
}
stop_one() { [ -f ".run/$1.pid" ] && { kill "$(cat ".run/$1.pid")" 2>/dev/null; rm -f ".run/$1.pid"; echo "  stopped $1"; }; }

case "${1:-}" in
  db-up)
    docker start "$C" >/dev/null 2>&1 || docker run -d --name "$C" -p 5434:5432 \
      -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" -e POSTGRES_DB=shop -v cs-pgdata:/var/lib/postgresql/data postgres:16 >/dev/null
    for _ in $(seq 1 30); do docker exec "$C" pg_isready -U postgres -d shop >/dev/null 2>&1 && break; sleep 1; done ;;
  reset)   # drop, recreate, seed: the known starting state for every run
    docker exec -i "$C" psql -U postgres -d shop -v ON_ERROR_STOP=1 -v toolbox_pw="$TOOLBOX_DB_PASSWORD" < db/seed.sql ;;
  psql)    shift; docker exec -i "$C" psql -U postgres -d shop "$@" ;;
  toolbox) exec npx -y @toolbox-sdk/server --config mcp_toolbox/tools.yaml --enable-api --address 127.0.0.1 --port "$TOOLBOX_PORT" ;;
  phoenix) PHOENIX_HOST=127.0.0.1 PHOENIX_PORT=6007 PHOENIX_GRPC_PORT=4327 PHOENIX_WORKING_DIR="$PWD/.phoenix" exec .venv/bin/phoenix serve ;;
  judge)   exec $PY guards/judge/service.py ;;
  masker)  exec $PY guards/masker/service.py ;;
  up)
    echo "starting services"
    "$0" db-up && echo "  ok    postgres"
    start toolbox npx -y @toolbox-sdk/server --config mcp_toolbox/tools.yaml --enable-api --address 127.0.0.1 --port "$TOOLBOX_PORT"
    wait_for toolbox "http://127.0.0.1:$TOOLBOX_PORT/api/toolset" 60 || exit 1
    start judge $PY guards/judge/service.py;   wait_for judge  "http://127.0.0.1:10002/health" || exit 1
    start masker $PY guards/masker/service.py; wait_for masker "http://127.0.0.1:10003/health" || exit 1
    PHOENIX_HOST=127.0.0.1 PHOENIX_PORT=6007 PHOENIX_GRPC_PORT=4327 PHOENIX_WORKING_DIR="$PWD/.phoenix" start phoenix .venv/bin/phoenix serve
    wait_for phoenix "http://127.0.0.1:6007/healthz" 60 || exit 1
    start web $PY -m uvicorn support.web:app --host 127.0.0.1 --port 8100 --log-level warning
    wait_for web "http://127.0.0.1:8100/health" 60 ;;
  down)    for n in web masker judge toolbox; do stop_one $n; done; echo "  (phoenix and postgres left running; ./run.sh stop-all to stop them too)" ;;
  stop-all) for n in web masker judge toolbox phoenix; do stop_one $n; done; docker stop "$C" >/dev/null && echo "  stopped postgres" ;;
  stop)    shift; for n in "$@"; do stop_one "$n"; done ;;
  status)
    docker exec "$C" pg_isready -U postgres -d shop >/dev/null 2>&1 && echo "  ok    postgres" || echo "  DOWN  postgres"
    for s in "toolbox http://127.0.0.1:$TOOLBOX_PORT/api/toolset" "judge http://127.0.0.1:10002/health" "masker http://127.0.0.1:10003/health" \
             "phoenix http://127.0.0.1:6007/healthz" "web http://127.0.0.1:8100/health"; do
      set -- $s; curl -fs -m 2 "$2" >/dev/null 2>&1 && echo "  ok    $1" || echo "  DOWN  $1"
    done ;;
  cli)     shift; exec $PY -m support.cli "$@" ;;
  web)     exec $PY -m uvicorn support.web:app --host 127.0.0.1 --port 8100 ;;
  eval)    shift; exec $PY -m eval.run "$@" ;;
  spend)   $PY -c "from support import budget as b; print(f\"today: \${b.today_spend():.4f} of \${b.CAP_USD:.2f} cap\")" ;;
  *) echo "usage: ./run.sh up | down | status | stop-all | reset | cli [--user EMAIL] [--events] | web | eval | psql [args]"; exit 1 ;;
esac
