#!/usr/bin/env bash
# WSL -> 算力平台 vLLM 隧道（autossh 自动重连，SSH 密钥免密）
#
# 用法:
#   bash tools/start_vllm_tunnel.sh start    # 后台启动（断线自动重连）
#   bash tools/start_vllm_tunnel.sh stop     # 停止
#   bash tools/start_vllm_tunnel.sh status   # 查看状态
#
# 转发: 本地 6006 -> 服务器 6006 (qwen3.5-2b-sft)
#       本地 6008 -> 服务器 6008 (qwen3.5-2b)
set -euo pipefail

HOST="root@connect.nmb2.seetacloud.com"
PORT="35547"
KEY="$HOME/.ssh/id_ed25519"
FORWARDS="-L 6006:127.0.0.1:6006 -L 6008:127.0.0.1:6008"
LOG="$HOME/vllm_tunnel.log"
PIDFILE="$HOME/.vllm_tunnel.pid"

start() {
  stop 2>/dev/null || true
  # AUTOSSH_GATETIME=0: 首次连接失败也立即重试
  AUTOSSH_GATETIME=0 setsid nohup autossh -M 0 -N \
    -o "ServerAliveInterval=30" \
    -o "ServerAliveCountMax=3" \
    -o "ExitOnForwardFailure=yes" \
    -o "StrictHostKeyChecking=accept-new" \
    -i "$KEY" \
    $FORWARDS -p "$PORT" "$HOST" > "$LOG" 2>&1 < /dev/null &
  echo $! > "$PIDFILE"
  echo "[tunnel] started (pid $(cat "$PIDFILE"))"
}

stop() {
  if [ -f "$PIDFILE" ]; then
    kill "$(cat "$PIDFILE")" 2>/dev/null || true
    rm -f "$PIDFILE"
  fi
  pkill -f "autossh -M 0 -N" 2>/dev/null || true
  echo "[tunnel] stopped"
}

status() {
  pids=$(pgrep -f "autossh -M 0 -N" || true)
  if [ -n "$pids" ]; then
    echo "[tunnel] running (pid $(echo "$pids" | sed -n 1p))"
  else
    echo "[tunnel] not running"
  fi
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) echo "usage: $0 {start|stop|status}"; exit 1 ;;
esac
