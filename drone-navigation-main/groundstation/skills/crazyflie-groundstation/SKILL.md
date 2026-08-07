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

## 截图并发送（微信等渠道）

用户要求"截一张图/拍照/看看画面"时：

1. 抓取地面站摄像头最新一帧：

```bash
curl -s http://127.0.0.1:18790/capture -o /tmp/gs_snapshot.jpg
```

2. 检查文件非空且是 JPEG（`file /tmp/gs_snapshot.jpg` 应显示 JPEG 图像数据；
   curl 返回 503 说明摄像头离线，如实告知用户）。
3. 调用你的**消息发送工具**（`message`），把 `/tmp/gs_snapshot.jpg` 作为
   媒体附件发送给**当前对话用户**，可附带一句简短说明（如"这是当前画面截图"）。

注意：截图来自 ESP32 摄像头；摄像头离线时接口返回 503，不要编造图片。

## 识别画面中的人（本地 YOLO）

用户要求"识别可疑人员 / 看看有没有人 / 检测画面"时，**唯一正确方式**是
调用地面站的 `POST /detect` 接口（见下）。**严禁**自行编写、下载或运行任何
检测脚本；**严禁**使用 cv2/其他检测方法自行分析画面；**严禁**启动后台进程
或子任务做检测——这些会极慢且经常失败。直接调接口、直接用返回结果。

1. 对当前帧做本地 YOLO 检测：

```bash
curl -s -X POST http://127.0.0.1:18790/detect -H 'Content-Type: application/json' -d '{"conf":0.4}'
```

2. 响应 JSON 含：`count`（人数）、`persons`（数组，每项 `bbox` + `confidence`）、
   `annotated_path`（标注了方框的图片路径，检测到人时有值）。
3. 检测到人（count>0）：把 `annotated_path` 图片发送给当前用户，并报告人数与
   置信度（如"检测到 2 人，最高置信度 0.87"）。
4. 未检测到人（count=0）：明确告知"当前画面未检测到人"，不要编造。
5. 接口返回 503/错误：如实说明（摄像头离线或检测器不可用），并建议用户
   检查摄像头画面与地面站日志。
6. 整个过程最多调用一次 `/detect`，拿到结果后立即发送图片并总结，
   不要重复检测、不要多次调用模型。

## 识别彩色物块（红色/绿色/蓝色）

用户要求"识别红色物块 / 找红色方块 / 看看有没有红色目标"时，调用颜色检测
接口（本地 OpenCV，无需模型，毫秒级）：

```bash
curl -s -X POST http://127.0.0.1:18790/detect_color -H 'Content-Type: application/json' -d '{"color":"red"}'
```

`color` 支持 `red` / `green` / `blue`。响应含 `count`（物块数量）、
`regions`（每个物块的 bbox、面积、占比）、`annotated_path`（画框图片路径）。
检测到物块：把 `annotated_path` 图片发给当前用户，报告数量与位置；
没有检测到：明确告知，不要编造。接口 503/错误时如实说明。

## 持续监控任务（定时巡逻）

用户要求"每 30 秒监控红色物块 / 持续检测，识别到才通知我 / 电量低自动停"时，
启动地面站的持续监控（由地面站后台线程执行，不占用对话）：

```bash
curl -s -X POST http://127.0.0.1:18790/monitor/start -H 'Content-Type: application/json' \
  -d '{"interval":30,"color":"red","target":"<当前微信用户ID>","battery_threshold":3.7}'
```

- `interval`：检测间隔秒数（最小 5，默认 30）。
- `color`：red/green/blue。
- `target`：接收通知的微信用户 ID（形如 `xxx@im.wechat`）。优先用当前对话
  用户；如果无法确定，让用户确认或留空（地面站会尝试从日志解析）。
- `battery_threshold`：电池低于该值（伏）自动休眠监控（默认 3.7）。
- 行为：每个周期检测一次；**只有识别到物块才推送微信消息**（附标注图）；
  电量低于阈值自动停止并推送休眠提示。

其他接口：

```bash
curl -s http://127.0.0.1:18790/monitor/status       # 查看监控状态
curl -s -X POST http://127.0.0.1:18790/monitor/stop -H 'Content-Type: application/json' -d '{"reason":"user stopped"}'
```

启动后立即告知用户："监控已启动，每 30 秒检测一次红色物块，识别到会推送；
电量低于 3.7V 自动休眠。" 不要反复查询状态或重复启动。

## 定时任务（每 N 秒发送固定内容）

用户要求"每 30 秒给我发一次 X / 定时发送"时，用 OpenClaw cron 创建任务。
**必须用 `--command` 固定输出，禁止用 `--message` 驱动 agent**——agent
驱动的任务每次都会自由发挥（表情、解释、废话），只有 `--command` 才能
保证推送内容就是用户要求的那句话，且不消耗模型。

```bash
openclaw cron add --name <任务名> --every 30s \
  --channel openclaw-weixin --to <当前微信用户ID> \
  --command 'echo 你好' --announce
```

- `--every`：间隔，支持秒（如 `30s`、`5m`、`1h`）。
- `--command 'echo <内容>'`：固定输出内容（要发的原文，例如 `echo 你好`）。
- `--to`：当前微信用户 ID（形如 `xxx@im.wechat`）；无法确定时让用户确认。
- `--announce`：把命令输出作为消息推送到微信。

管理任务：

```bash
openclaw cron list                    # 查看所有任务
openclaw cron rm --name <任务名>       # 删除任务（停止）
```

创建后回复用户**只允许一行**，格式：
`已创建定时任务：<任务名>，每 <间隔> 发送"<内容>"。停止请说"停止任务 <任务名>"。`
禁止添加表情、解释、Markdown 或任何额外文字。

## 工具要点

- `get_status`：起飞前必调。检查 `connected`（是否连接）、`locked`（是否锁定）、
  `battery_v`（电压）、`flying`（是否飞行中）。
- `takeoff(height)`：起飞并悬停，height 建议 0.3–0.5 m。
- `move(vx, vy, vz, yawrate, duration)`：速度移动，`duration` 必须 ≤ 2 秒。
- `land()`：受控降落，任务结束必须调用。
- `hover()`：悬停。
- `stop()` / `estop()`：立即切电机（空中会坠落），仅紧急情况使用；
  `estop` 后地面站会锁存，`get_status` 显示 `estop_latched=true`，
   takeoff/spin_test 将被拒绝；解除需由操作员重启无人机或在地面站
   GUI 点击"解除锁存"，agent 没有任何解锁接口。
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
8. 急停（`estop`）后地面站进入锁存：任何通道的 takeoff/spin_test 都会被
   拒绝。解锁只有两种途径：① 对无人机断电重启（掉线超过 10 秒后重连）
   自动解锁；② 操作员在地面站 GUI 人工点击"解除锁存"。agent 没有任何
   解锁接口，看到 `estop_latched=true` 时先请用户处理（重启无人机或点击
   解除锁存），不要反复尝试起飞，也不要编造解锁命令。

## 响应格式

- 回答用**纯文本**，禁止 Markdown（不要 `**`、`` ` ``、表格、列表符号）。
- 中文优先，简短直接：先给结论，再给必要的数据（电压、高度、位置）。
- 接口返回 JSON；只向用户展示可读的摘要（电压、高度、位置、是否成功），
  不要原样粘贴大段 JSON。
