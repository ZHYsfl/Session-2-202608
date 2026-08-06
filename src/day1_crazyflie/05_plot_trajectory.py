#!/usr/bin/env python3
"""05 — 把 04 输出的轨迹 CSV 画成图（供日结/论文使用）。

用法:
    python 05_plot_trajectory.py mission_dry.csv [out.png]

输出:
    横向图（XY 俯视 + XYZ 随时间）保存为 PNG；不传输出名则直接显示窗口。
"""
import sys

import matplotlib
import matplotlib.pyplot as plt
import csv


def load(csv_path):
    ts, xs, ys, zs, yaws = [], [], [], [], []
    with open(csv_path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            ts.append(float(row['t']))
            xs.append(float(row['x']))
            ys.append(float(row['y']))
            zs.append(float(row['z']))
            yaws.append(float(row['yaw']))
    return ts, xs, ys, zs, yaws


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    csv_path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else None

    ts, xs, ys, zs, yaws = load(csv_path)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))

    # Left: XY top-down view
    ax = axes[0]
    ax.plot(xs, ys, '-o', ms=2.5, lw=1.2, label='trajectory')
    ax.plot(xs[0], ys[0], 'gs', label='take-off')
    ax.plot(xs[-1], ys[-1], 'r^', label='end')
    ax.set_xlabel('x (m)'); ax.set_ylabel('y (m)')
    ax.set_title('Horizontal trajectory (top view)')
    ax.grid(True, alpha=0.3); ax.axis('equal'); ax.legend()

    # Right: XYZ vs time
    ax = axes[1]
    ax.plot(ts, xs, label='x', lw=1.2)
    ax.plot(ts, ys, label='y', lw=1.2)
    ax.plot(ts, zs, label='z', lw=1.2)
    ax.set_xlabel('time (s)'); ax.set_ylabel('position (m)')
    ax.set_title('Position vs time')
    ax.grid(True, alpha=0.3); ax.legend()

    fig.suptitle(f'Crazyflie trajectory — {csv_path}')
    fig.tight_layout()

    if out_path:
        fig.savefig(out_path, dpi=150)
        print(f'[+] 已保存: {out_path}')
    else:
        plt.show()


if __name__ == '__main__':
    main()
