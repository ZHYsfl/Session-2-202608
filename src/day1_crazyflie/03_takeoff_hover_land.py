#!/usr/bin/env python3
"""03 — 基础技能(60分)：起飞 → 悬停 ≥10 秒（无明显漂移）→ 降落。

用法:
    python 03_takeoff_hover_land.py --hover 12 --height 0.5
    python 03_takeoff_hover_land.py --dry      # 无硬件仿真跑一遍流程

说明:
    * 悬停稳定性依赖位置估计。若无人机只带 IMU（无 Flow deck），它会缓慢漂移，
      建议加装 Flow deck v2 以真正“钉”在空中。
    * 脚本全程打印当前高度与水平漂移，用于验收记录。
"""
import argparse
import time

import cflib.crtp
from cflib.positioning.motion_commander import MotionCommander

from cf_utils import first_available_uri, open_link
from telemetry import Telemetry
from sim import SimMotionCommander


def hover_for(seconds, height, pos_fn, drift_log):
    """保持悬停 seconds 秒，周期性记录高度和水平漂移。"""
    t0 = time.time()
    while time.time() - t0 < seconds:
        x, y, z = pos_fn()
        drift = (x * x + y * y) ** 0.5
        print(f'    悬停中  t={time.time() - t0:5.1f}s  '
              f'高度={z:.3f} m  水平漂移={drift:.3f} m', flush=True)
        drift_log.append((time.time() - t0, z, drift))
        time.sleep(1.0)


def main():
    ap = argparse.ArgumentParser(description='起飞 / 悬停 / 降落')
    ap.add_argument('--hover', type=float, default=10.0, help='悬停时长(秒)')
    ap.add_argument('--height', type=float, default=0.5, help='悬停高度(米)')
    ap.add_argument('--dry', action='store_true', help='无硬件仿真模式')
    ap.add_argument('--uri', default=None, help='Crazyflie URI')
    args = ap.parse_args()

    drift_log = []

    if args.dry:
        print('[*] 仿真模式（无硬件）')
        with SimMotionCommander(default_height=args.height) as mc:
            print(f'[+] 起飞并悬停到 {args.height} m ...')
            hover_for(args.hover, args.height, lambda: mc.position, drift_log)
        mc.print_commands()
        print('[+] 仿真悬停完成。')
        return

    cflib.crtp.init_drivers()
    uri = args.uri or first_available_uri()
    print(f'[*] 目标 URI: {uri}')

    with open_link(uri) as scf:
        tel = Telemetry(scf.cf, period_ms=100)
        tel.start()

        def pos_fn():
            return (tel.get('stateEstimate.x', 0.0),
                    tel.get('stateEstimate.y', 0.0),
                    tel.get('stateEstimate.z', 0.0))

        with MotionCommander(scf, default_height=args.height) as mc:
            print(f'[+] 起飞并悬停到 {args.height} m ...')
            hover_for(args.hover, args.height, pos_fn, drift_log)

        tel.stop()

    print('[+] 任务完成：起飞 → 悬停 → 降落。')
    if drift_log:
        max_drift = max(d for _, _, d in drift_log)
        print(f'[+] 悬停期间最大水平漂移 = {max_drift:.3f} m（验收时关注 <0.3 m）')


if __name__ == '__main__':
    main()
