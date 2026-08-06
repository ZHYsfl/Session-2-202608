---
name: crazyflie-groundstation
description: 通过 Crazyflie QT 地面站控制无人机：状态检查、起飞、移动、降落、急停与旋翼测试。当用户提到地面站、无人机、起飞、降落、急停时使用。
---

# Crazyflie 地面站操作技能

本技能教智能体如何通过地面站安全地操作 Crazyflie 无人机。地面站已把
无人机操作暴露为标准 function tools（`get_status` / `takeoff` / `land` /
`hover` / `stop` / `estop` / `move` / `spin_test`），**优先直接调用工具**，
不要自己拼 `curl`。工具 schema 随聊天请求自动提供，这里只记要点。

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
- 工具执行结果会以 JSON 返回；只向用户展示可读的摘要，不要原样粘贴大段 JSON。
