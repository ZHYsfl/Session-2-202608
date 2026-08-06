#!/usr/bin/env python3
"""04 — 进阶技能(80分)：虚拟围栏内的全套飞行动作。

动作清单（对应任务要求）:
    * 起飞 / 降落
    * 前进 / 后退
    * 上升 / 下降（升降）
    * 左转 / 右转（转弯）
    * 加速 / 减速（速度剖面：低速段 → 高速段 → 减速停止）

安全设计:
    1. 每次平移前用虚拟围栏(clamp_displacement)收紧位移，保证目标点在
       x/y/z 边界内 —— 无人机根本不会被“派去”撞围栏。
    2. FenceMonitor 后台线程实时盯位置，一旦越界立即急停并触发紧急降落。
    3. 每个动作都响应 abort 事件，中途可立即刹车。

用法:
    python 04_flight_mission.py --dry          # 无硬件仿真（验证逻辑）
    python 04_flight_mission.py                # 真实飞行（默认 2m x 2m x 1.2m 围栏）
    python 04_flight_mission.py --flow --csv mission.csv   # 有 Flow deck 时用实测位置
"""
import argparse
import csv
import math
import threading
import time

import cflib.crtp
from cflib.positioning.motion_commander import MotionCommander

from cf_utils import first_available_uri, open_link
from sim import SimMotionCommander
from telemetry import Telemetry
from virtual_fence import VirtualFence, FenceMonitor, PositionIntegrator


def world_to_body(dxw, dyw, yaw_deg):
    """把世界系水平位移转为机体系水平位移（绕 yaw 反旋转）。"""
    r = math.radians(yaw_deg)
    c, s = math.cos(r), math.sin(r)
    return dxw * c + dyw * s, -dxw * s + dyw * c


def _run_velocity(mc, start_fn, duration, abort):
    """执行一个限时速度动作，随时响应围栏 abort 事件。"""
    start_fn()
    end = time.time() + duration
    while time.time() < end:
        if abort.is_set():
            mc.stop()
            return False
        time.sleep(0.05)
    mc.stop()
    return True


def do_translation(mc, fence, state_fn, abort, dx, dy, dz, velocity, label):
    """围栏收紧后的平移动作。dx/dy/dz 为世界系位移(米)。"""
    x, y, z, yaw = state_fn()
    cdx, cdy, cdz = fence.clamp_displacement(dx, dy, dz, x, y, z)
    dist = math.hypot(cdx, cdy, cdz)
    if dist < 0.02:
        print(f'  - 「{label}」被围栏拦截：当前位置 ({x:.2f},{y:.2f},{z:.2f}) 已无空间')
        return True
    print(f'  -> {label}: 请求({dx:+.2f},{dy:+.2f},{dz:+.2f})m → '
          f'围栏后({cdx:+.2f},{cdy:+.2f},{cdz:+.2f})m，耗时{dist / velocity:.1f}s')
    # 世界系位移 -> 机体系速度（保持沿期望的世界方向飞）
    bvx, bvy = world_to_body(cdx, cdy, yaw)
    ok = _run_velocity(
        mc,
        lambda: mc.start_linear_motion(velocity * bvx / dist,
                                       velocity * bvy / dist,
                                       velocity * cdz / dist),
        dist / velocity, abort)
    return ok


def do_turn(mc, abort, angle_deg, rate=90.0, direction='left'):
    """原地转弯，direction='left'/'right'。"""
    start = (mc.start_turn_left if direction == 'left' else mc.start_turn_right)
    print(f'  -> 转弯: {direction} {angle_deg}°（速度 {rate}°/s）')
    return _run_velocity(mc, lambda: start(rate), angle_deg / rate, abort)


def do_speed_profile(mc, fence, state_fn, abort, label, stages, direction=1.0):
    """加减速演示：按 [(速度, 时长), ...] 依次执行，围栏限制向前空间。"""
    print(f'  -> {label}: 速度剖面 {stages}')
    for v, dur in stages:
        x, y, z, _ = state_fn()
        # 近似：向前(+x)/向后(-x)方向还有多少空间（假定 yaw≈0）
        if v > 0:
            room = fence.x_max - fence.margin - x
        elif v < 0:
            room = (fence.x_min + fence.margin) - x
        else:
            room = float('inf')
        if room < 0.02:
            print('  - 速度剖面被围栏提前终止（前方无空间）')
            break
        dur = min(dur, room / abs(v)) if v != 0 else dur
        if dur <= 0:
            break
        print(f'      v={v:+.1f} m/s，{dur:.1f}s'
              + ('（围栏收紧）' if dur < 1e-6 else ''))
        if not _run_velocity(mc, lambda: mc.start_forward(v), dur, abort):
            break
    mc.stop()


def run_mission(mc, fence, state_fn, abort, recorder=None):
    """执行完整任务序列，返回 True 表示未触发围栏急停。"""
    print(f'[+] 围栏范围: {fence.describe()}')
    # 起飞由上下文管理器(with mc:)自动完成到 default_height=0.5 m
    print('[+] 起飞 (0.5 m) ...')
    _log_pos(state_fn, '起飞点')

    print('[+] 基础悬停演示 5 s ...')
    time.sleep(5)
    _log_pos(state_fn, '悬停后')

    # 前进 / 后退
    do_translation(mc, fence, state_fn, abort, 0.6, 0.0, 0.0, 0.25, '前进 0.6 m')
    if abort.is_set():
        return False
    _log_pos(state_fn, '前进后')
    do_translation(mc, fence, state_fn, abort, -0.6, 0.0, 0.0, 0.25, '后退 0.6 m')
    if abort.is_set():
        return False
    _log_pos(state_fn, '后退后')

    # 上升 / 下降
    do_translation(mc, fence, state_fn, abort, 0.0, 0.0, 0.3, 0.25, '上升 0.3 m')
    if abort.is_set():
        return False
    _log_pos(state_fn, '上升后')
    do_translation(mc, fence, state_fn, abort, 0.0, 0.0, -0.3, 0.25, '下降 0.3 m')
    if abort.is_set():
        return False
    _log_pos(state_fn, '下降后')

    # 转弯（左 90，右 90，回到原朝向）
    do_turn(mc, abort, 90.0, direction='left')
    if abort.is_set():
        return False
    do_turn(mc, abort, 90.0, direction='right')
    if abort.is_set():
        return False
    _log_pos(state_fn, '转弯后')

    # 加速 / 减速：低速前进 -> 高速前进 -> 停止（含减速）
    do_speed_profile(mc, fence, state_fn, abort, '加速/减速（前进）',
                     [(0.2, 1.5), (0.5, 1.5)])
    if abort.is_set():
        return False
    _log_pos(state_fn, '加减速后')

    print('[+] 收尾悬停 3 s ...')
    time.sleep(3)
    _log_pos(state_fn, '降落前')
    mc.land()
    print('[+] 降落完成。')
    return True


def _log_pos(state_fn, label):
    x, y, z, yaw = state_fn()
    print(f'      [{label}]  位置=({x:.2f}, {y:.2f}, {z:.2f}) m   yaw={yaw:.1f}°')


class TrajectoryRecorder:
    """后台线程以 10 Hz 记录轨迹到 CSV（真实/仿真通用）。"""

    def __init__(self, path, state_fn):
        self._f = open(path, 'w', newline='', encoding='utf-8')
        self._w = csv.writer(self._f)
        self._w.writerow(['t', 'x', 'y', 'z', 'yaw'])
        self._state_fn = state_fn
        self._t0 = time.time()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            self.tick()
            time.sleep(0.1)

    def tick(self):
        x, y, z, yaw = self._state_fn()
        self._w.writerow([f'{time.time() - self._t0:.3f}',
                          f'{x:.4f}', f'{y:.4f}', f'{z:.4f}', f'{yaw:.1f}'])

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._f.close()


def main():
    ap = argparse.ArgumentParser(description='虚拟围栏飞行任务（进阶）')
    ap.add_argument('--dry', action='store_true', help='无硬件仿真')
    ap.add_argument('--flow', action='store_true', help='已装 Flow deck，用实测 x/y')
    ap.add_argument('--uri', default=None, help='Crazyflie URI')
    ap.add_argument('--csv', default=None, help='轨迹输出 CSV 路径')
    ap.add_argument('--fence', default='2,2,1.2',
                    help='围栏尺寸 宽,深,高(米)，默认 2,2,1.2')
    args = ap.parse_args()

    w, d, h = (float(v) for v in args.fence.split(','))
    fence = VirtualFence(-w / 2, w / 2, -d / 2, d / 2, 0.05, h)

    abort = threading.Event()
    recorder = None

    if args.dry:
        print('[==== 仿真模式（无硬件）====]')
        mc = SimMotionCommander(default_height=0.5)
        with mc:
            state_fn = lambda: (*mc.position, mc.yaw_deg)
            if args.csv:
                recorder = TrajectoryRecorder(args.csv, state_fn)
                recorder.start()
            ok = run_mission(mc, fence, state_fn, abort)
        if recorder:
            recorder.close()
        mc.print_commands()
        print(f'[+] 仿真任务结束，结果: {"成功" if ok else "触发围栏"}')
        return

    print(f'[*] 目标 URI: {args.uri or first_available_uri()}')
    cflib.crtp.init_drivers()
    uri = args.uri or first_available_uri()

    with open_link(uri) as scf:
        tel = Telemetry(scf.cf, period_ms=50, csv_path=args.csv and args.csv + '.raw')
        tel.start()
        integrator = PositionIntegrator(tel)

        def state_fn():
            if args.flow:
                x = tel.get('stateEstimate.x', 0.0)
                y = tel.get('stateEstimate.y', 0.0)
            else:
                x, y = integrator.update()
            return (x, y,
                    tel.get('stateEstimate.z', 0.0),
                    tel.get('stateEstimate.yaw', 0.0))

        with MotionCommander(scf, default_height=0.5) as mc:
            monitor = FenceMonitor(
                fence, state_fn, abort,
                on_violation=lambda pos: print(f'\n  !! 围栏越界 @ {pos}，急停并准备降落'),
                stop_cmd=mc.stop)
            monitor.start()
            if args.csv:
                recorder = TrajectoryRecorder(args.csv, state_fn)
                recorder.start()
            try:
                ok = run_mission(mc, fence, state_fn, abort)
            finally:
                monitor.stop()
                if recorder:
                    recorder.close()
            if not ok:
                print('[!] 任务因围栏触发提前结束。')

    print('[+] 真实任务结束。')


if __name__ == '__main__':
    main()
