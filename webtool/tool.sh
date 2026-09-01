#!/usr/bin/env bash
# DOM 한글패치 웹 툴 시작/멈춤 스크립트
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$DIR/.server.pid"
LOG_FILE="$DIR/server.log"
PORT="${PORT:-4000}"

is_running() {
  [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

ensure_deps() {
  if ! python3 -c "import flask, PIL" >/dev/null 2>&1; then
    echo "필요한 파이썬 패키지를 설치합니다..."
    python3 -m pip install -r "$DIR/requirements.txt"
  fi
}

start() {
  if is_running; then
    echo "이미 실행 중입니다 (PID $(cat "$PID_FILE")), http://localhost:$PORT"
    exit 0
  fi
  ensure_deps
  cd "$DIR"
  PORT="$PORT" nohup python3 server_py/app.py > "$LOG_FILE" 2>&1 < /dev/null &
  echo $! > "$PID_FILE"
  disown
  sleep 1
  if is_running; then
    echo "서버 시작됨 (PID $(cat "$PID_FILE")), http://localhost:$PORT"
  else
    echo "서버 시작 실패. 로그:"
    cat "$LOG_FILE" 2>/dev/null || true
    rm -f "$PID_FILE"
    exit 1
  fi
}

stop() {
  if ! is_running; then
    echo "실행 중이 아닙니다"
    rm -f "$PID_FILE"
    exit 0
  fi
  kill "$(cat "$PID_FILE")"
  rm -f "$PID_FILE"
  echo "서버 종료됨"
}

status() {
  if is_running; then
    echo "실행 중 (PID $(cat "$PID_FILE")), http://localhost:$PORT"
  else
    echo "중지됨"
  fi
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  restart) is_running && stop; start ;;
  status) status ;;
  *)
    echo "사용법: $0 {start|stop|restart|status}"
    exit 1
    ;;
esac
