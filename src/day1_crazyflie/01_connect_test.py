#!/usr/bin/env python3
"""01 — 连接测试：扫描并连接到一架 Crazyflie。

用法:
    python 01_connect_test.py                # 自动扫描并连接第一架
    python 01_connect_test.py radio://0/80/2M/E7E7E7E7E7   # 指定 URI

连接成功后会打印固件/硬件参数并读取一小段遥测，然后正常断开。
"""
import sys
import time

from cf_utils import init_drivers, first_available_uri, open_link
from telemetry import Telemetry


def read_params(cf):
    """读取若干已知的参数（不存在就跳过，不影响主流程）。"""
    results = {}
    for name in ('system.hwType', 'system.hwRev', 'system.nbrOfReset'):
        try:
            results[name] = cf.param.get_value(name)
        except Exception:
            pass
    return results


def main():
    init_drivers()

    uri = sys.argv[1] if len(sys.argv) > 1 else first_available_uri()
    print(f'[*] 目标 URI: {uri}')

    with open_link(uri) as scf:
        print('[+] 已连接！')
        print(f'[*] 实际链路: {scf.cf.link_uri}')

        for name, value in read_params(scf.cf).items():
            print(f'[*] {name:<24} = {value}')

        # 订阅一小段遥测，验证数据通道可用
        tel = Telemetry(scf.cf, period_ms=200)
        tel.start()
        time.sleep(1.0)
        print('[*] 遥测样例（1 秒内的最新值）:')
        for var in ('stateEstimate.z', 'stateEstimate.yaw', 'stateEstimate.vx', 'pm.vbat'):
            print(f'    {var:<22} = {tel.get(var)}')
        tel.stop()

    print('[+] 已断开，连接测试通过。')


if __name__ == '__main__':
    main()
