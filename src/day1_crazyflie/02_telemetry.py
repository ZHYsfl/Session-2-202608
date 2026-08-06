#!/usr/bin/env python3
"""02 — 实时遥测：接收无人机的高度、速度、方向（yaw）、电池电压。

用法:
    python 02_telemetry.py --seconds 10 --csv telemetry.csv

连接后以 20 Hz 刷新一屏实时数据。飞行参数（高度/速度/方向）即任务要求里
“接收飞行参数”的部分；``--csv`` 会把原始数据落盘，方便后续画图写总结。
"""
import argparse
import time

from cf_utils import init_drivers, first_available_uri, open_link
from telemetry import Telemetry


def fmt(v, width=8):
    return f'{v:>{width}.3f}' if v is not None else f'{"---":>{width}}'


def main():
    ap = argparse.ArgumentParser(description='Crazyflie 实时遥测')
    ap.add_argument('--uri', default=None, help='Crazyflie URI（默认自动扫描）')
    ap.add_argument('--seconds', type=float, default=10.0, help='采集时长（秒）')
    ap.add_argument('--csv', default=None, help='输出 CSV 路径，例如 telemetry.csv')
    args = ap.parse_args()

    init_drivers()
    uri = args.uri or first_available_uri()
    print(f'[*] 目标 URI: {uri}')

    with open_link(uri) as scf:
        tel = Telemetry(scf.cf, period_ms=50, csv_path=args.csv)
        tel.start()

        print('[+] 开始采集遥测，Ctrl+C 提前结束。\n')
        deadline = time.time() + args.seconds
        try:
            while time.time() < deadline:
                z = tel.get('stateEstimate.z')
                vx = tel.get('stateEstimate.vx')
                vy = tel.get('stateEstimate.vy')
                vz = tel.get('stateEstimate.vz')
                yaw = tel.get('stateEstimate.yaw')
                roll = tel.get('stateEstimate.roll')
                pitch = tel.get('stateEstimate.pitch')
                vbat = tel.get('pm.vbat')
                print(
                    f'\r  高度(z)={fmt(z)} m | '
                    f'速度=(vx {fmt(vx)}, vy {fmt(vy)}, vz {fmt(vz)}) m/s | '
                    f'方向(yaw)={fmt(yaw, 7)}° | 姿态=({fmt(roll, 6)}°, {fmt(pitch, 6)}°) | '
                    f'电压={fmt(vbat, 5)} V',
                    end='', flush=True)
                time.sleep(0.05)
        except KeyboardInterrupt:
            pass
        finally:
            print()
            tel.stop()

    print('[+] 采集结束。')


if __name__ == '__main__':
    main()
