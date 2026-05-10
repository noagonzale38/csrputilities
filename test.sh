#!/usr/bin/env bash
set -euxo pipefail

echo "=== system before build ==="
date
free -h
df -h
df -i
ulimit -a
node -v
npm -v
npx next --version || true

echo "=== starting build ==="

(
  while true; do
    echo "----- $(date) -----"
    free -h
    df -h /
    ps -eo pid,ppid,cmd,%mem,%cpu,rss --sort=-rss | head -25
    vmstat 1 5
    sleep 10
  done
) >> /var/log/next-build-watch.log 2>&1 &

WATCH_PID=$!

npm run build >> /var/log/next-build.log 2>&1

kill "$WATCH_PID" || true
