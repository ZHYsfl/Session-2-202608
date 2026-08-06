#!/bin/bash
# 全套服务停止（WSL 内执行）：mediamtx -> synapse -> uvicorn -> openclaw -> PG
# 用法: wsl -d Ubuntu-24.04 -- bash /mnt/d/AllKindsofFiles/OfflinePractice_2026_Summer/Session-2-202608/drone-navigation-main/deployment/scripts/stop-all.sh

echo "stopping mediamtx"
pkill -x mediamtx 2>/dev/null
echo "stopping synapse"
pkill -f '[s]ynapse.app.homeserver' 2>/dev/null
echo "stopping uvicorn"
pkill -f '[u]vicorn app.main:app' 2>/dev/null
echo "stopping openclaw"
export XDG_RUNTIME_DIR=/run/user/1000
systemctl --user stop openclaw-gateway.service 2>/dev/null || true
pkill -f '[o]penclaw/dist/index.js' 2>/dev/null
sleep 1
OPENCLAW_PID=$(ss -tlnp | grep ':18789' | grep -oP 'pid=\K[0-9]+' | head -1)
if [ -n "$OPENCLAW_PID" ]; then
  echo "openclaw still alive (pid $OPENCLAW_PID), kill -9"
  kill -9 "$OPENCLAW_PID"
  # kill 会触发 systemd Restart=always 拉起，需再次 stop 才能压住（2026-08-06 实测竞态）
  systemctl --user stop openclaw-gateway.service 2>/dev/null || true
fi
echo "stopping postgresql (:5433)"
/usr/lib/postgresql/16/bin/pg_ctl -D ~/pgdata stop 2>&1 || true
sleep 1
echo "=== remaining app listeners ==="
ss -tln | grep -E ':(5433|8000|8008|18789|8888|8889|9997)' || echo "none"
