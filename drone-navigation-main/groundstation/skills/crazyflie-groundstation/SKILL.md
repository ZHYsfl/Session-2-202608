---
name: crazyflie-groundstation
description: 通过 Crazyflie QT 地面站控制无人机：状态检查、起飞、移动、降落、急停与旋翼测试。当用户提到地面站、无人机、起飞、降落、急停时使用。
---

# Crazyflie 地面站操作技能

本技能教智能体如何通过地面站安全地操作 Crazyflie 无人机。地面站提供
两种等价的操作方式，选择当前会话可用的那种：

- **客户端工具**（地面站 GUI 聊天面板）：工具 `get_status` / `takeoff` /
  `land` / `hover` / `stop` / `estop` / `move` / `spin_test` 随请求自动提供，
  直接调用即可，不要拼 `curl`。
- **HTTP 接口**（微信等无客户端工具的渠道）：用 `curl` 调用本机地面站
  服务 `http://127.0.0.1:18790`，见下节。

## HTTP 接口（微信/无工具渠道）

地面站命令服务监听 `127.0.0.1:18790`。查看状态：

```bash
curl -s http://127.0.0.1:18790/status
```

发送命令（`action` 必填）：

```bash
curl -s -X POST http://127.0.0.1:18790/command -H 'Content-Type: application/json' -d '{"action":"takeoff","height":0.3}'
curl -s -X POST http://127.0.0.1:18790/command -H 'Content-Type: application/json' -d '{"action":"move","vx":0.3,"duration":1.5}'
curl -s -X POST http://127.0.0.1:18790/command -H 'Content-Type: application/json' -d '{"action":"land"}'
curl -s -X POST http://127.0.0.1:18790/command -H 'Content-Type: application/json' -d '{"action":"hover"}'
curl -s -X POST http://127.0.0.1:18790/command -H 'Content-Type: application/json' -d '{"action":"stop"}'
curl -s -X POST http://127.0.0.1:18790/command -H 'Content-Type: application/json' -d '{"action":"estop"}'
curl -s -X POST http://127.0.0.1:18790/command -H 'Content-Type: application/json' -d '{"action":"spin_test","power":4000,"duration":2}'
```

若 `127.0.0.1:18790` 不可达（连接拒绝），说明地面站服务没在运行：请用户
启动 `python cli.py serve` 或打开地面站 GUI，不要继续尝试飞行。

## 工具要点

- `get_status`：起飞前必调。检查 `connected`（是否连接）、`locked`（是否锁定）、
  `battery_v`（电压）、`flying`（是否飞行中）。
- `takeoff(height)`：起飞并悬停，height 建议 0.3–0.5 m。
- `move(vx, vy, vz, yawrate, duration)`：速度移动，`duration` 必须 ≤ 2 秒。
- `land()`：受控降落，任务结束必须调用。
- `hover()`：悬停。
- `stop()` / `estop()`：立即切电机（空中会坠落），仅紧急情况使用。
- `spin_test(power, duration)`：旋翼逐个慢速测试（m1→m4），起飞前必做。

## 安全规则（强制）

1. 起飞前先 `get_status`：`connected=true`、`locked=false`、
   `battery_v >= 3.9`，任何一项不满足就停止操作并告知用户。
2. 飞行前做旋翼测试（`spin_test`，power=4000）；桨叶无缺损、安装正确。
3. `move` 的 `duration` 不超过 2 秒；每次移动后 `get_status` 确认位置和高度。
4. 结束必须 `land`，确认 `flying=false` 才算完成。
5. 失控、倾斜过大、接近障碍物、通讯不稳 → 立即 `estop`（坠机式急停，仅紧急时用）。
6. 一个时刻只有一个进程占用无线电；操作前确认 bridge、GUI、CLI 没有同时在跑。
7. 已在飞行时不要重复 `takeoff`，先 `land` 再起飞。

## 响应格式

- 回答用**纯文本**，禁止 Markdown（不要 `**`、`` ` ``、表格、列表符号）。
- 中文优先，简短直接：先给结论，再给必要的数据（电压、高度、位置）。
- 接口返回 JSON；只向用户展示可读的摘要（电压、高度、位置、是否成功），
  不要原样粘贴大段 JSON。
