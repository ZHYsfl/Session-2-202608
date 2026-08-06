#!/bin/bash
# 全套服务启动（WSL 内执行）：PG -> uvicorn -> synapse -> openclaw -> mediamtx
# 用法: wsl -d Ubuntu-24.04 -- bash /mnt/d/AllKindsofFiles/OfflinePractice_2026_Summer/Session-2-202608/drone-navigation-main/deployment/scripts/start-all.sh
# 注意: 直接 wsl bash -c 的桥接会丢失 < > 2>&1 重定向，必须用脚本文件方式运行
# 幂等: 已监听的服务会跳过。mediamtx 是最后一个后台任务，启动后必须等监听确认再退出
#       （否则脚本秒退时 fork->exec 窗口内的子进程可能被会话收尾回收，实测 2026-08-05）

echo "[1/5] PostgreSQL (:5433)"
/usr/lib/postgresql/16/bin/pg_ctl -D ~/pgdata start -l ~/pgdata/logfile 2>&1 || true

echo "[2/5] uvicorn backend (:8000)"
if ss -tln | grep -q ':8000'; then
  echo "uvicorn already up, skip"
else
  cd /mnt/d/AllKindsofFiles/OfflinePractice_2026_Summer/Session-2-202608/drone-navigation-main/server || exit 1
  setsid nohup .venv/bin/uvicorn app.main:app --reload --port 8000 > ~/server-uvicorn.log 2>&1 < /dev/null &
fi

echo "[3/5] Synapse (:8008)"
if ss -tln | grep -q ':8008'; then
  echo "synapse already up, skip"
else
  setsid nohup ~/synapse-venv/bin/python -m synapse.app.homeserver -c ~/synapse-data/homeserver.yaml > ~/synapse.log 2>&1 < /dev/null &
fi

echo "[4/5] OpenClaw gateway (:18789)"
export XDG_RUNTIME_DIR=/run/user/1000
if systemctl --user start openclaw-gateway.service 2>/dev/null; then
  echo "openclaw started via systemd user service"
else
  PATH=/home/yyrxiaohei/node-v22.23.2-linux-x64/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin setsid nohup /home/yyrxiaohei/node-v22.23.2-linux-x64/bin/openclaw gateway --port 18789 > ~/openclaw-gateway.log 2>&1 < /dev/null &
fi

echo "[5/5] MediaMTX (:8889/8888/9997)"
if ss -tln | grep -q ':8889'; then
  echo "mediamtx already up, skip"
else
  cd ~/mediamtx_v1.9.0 || exit 1
  setsid nohup ./mediamtx > ~/mediamtx.log 2>&1 < /dev/null &
  for i in {1..15}; do
    if ss -tln | grep -q ':8889'; then echo "mediamtx listening"; break; fi
    sleep 1
  done
  ss -tln | grep -q ':8889' || echo "WARN: mediamtx not listening after 15s, check ~/mediamtx.log"
fi

sleep 2
echo "ALL-LAUNCHED"
