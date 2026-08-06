#!/bin/bash
# 全套服务健康检查（WSL 内执行）: 轮询 uvicorn /docs 并列出应用监听端口
# 用法: wsl -d Ubuntu-24.04 -- bash /mnt/d/AllKindsofFiles/OfflinePractice_2026_Summer/Session-2-202608/drone-navigation-main/deployment/scripts/verify-stack.sh

echo "polling uvicorn /docs (max 60s)..."
for i in {1..60}; do
  code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/docs 2>/dev/null)
  if [ "$code" = "200" ]; then
    echo "uvicorn /docs 200 after ~${i}s"
    break
  fi
  sleep 1
done

echo "=== WSL app listeners ==="
ss -tln | grep -E ':(5433|8000|8008|18789|8888|8889|9997)' || echo "none"

echo "=== MediaMTX paths ==="
curl -s http://127.0.0.1:9997/v3/paths/list
echo
