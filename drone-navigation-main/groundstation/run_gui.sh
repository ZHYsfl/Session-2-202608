#!/bin/bash
# 启动 Crazyflie 地面站（含中文输入法支持）
# 用法: bash run_gui.sh

export GTK_IM_MODULE=ibus
export QT_IM_MODULE=ibus
export XMODIFIERS=@im=ibus

# 确保 ibus 在运行（WSL 无桌面，需要手动启动）
if ! pgrep -x ibus-daemon > /dev/null; then
  if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
    eval "$(dbus-launch --sh-syntax)"
    export DBUS_SESSION_BUS_ADDRESS
  fi
  ibus-daemon -drx > /tmp/ibus.log 2>&1 &
  sleep 2
fi

cd "$(dirname "$0")"
exec python main.py
