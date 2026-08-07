# OpenClaw 操作 Crazyflie：地面站接口

地面站提供三种方式让 OpenClaw 操作无人机：**一次性 CLI 命令**、
**长驻 HTTP 服务**、**GUI 内置聊天面板**。三者共用同一个控制器和同一套
安全模型，二选一即可，**不要同时跑两个占用无线电的进程**（Crazyradio
同一时间只能被一个进程占用）。

## 方式一：一次性 CLI 命令

在 WSL 终端（`conda activate drone-navigation` 后）执行：

```bash
cd ~/drone-navigation/groundstation

python cli.py status                    # 查看连接、电池、锁定、位置
python cli.py takeoff --height 0.4      # 起飞并悬停
python cli.py move --vx 0.3 --duration 1.5   # 以 0.3 m/s 前进 1.5 秒
python cli.py move --vz 0.2 --duration 1.0   # 上升 0.2 m/s 1 秒
python cli.py land                      # 受控降落
python cli.py estop                     # 紧急切电机（会坠机）
```

每条命令输出一行 JSON（最新遥测快照），OpenClaw 解析 `status` 字段即可。

## 方式二：长驻 HTTP 服务

```bash
python cli.py serve                     # 默认 127.0.0.1:18790
```

### `GET /health`

```json
{"ok": true, "service": "groundstation", "actions": ["takeoff", "land", "hover", "stop", "estop", "move"]}
```

### `GET /status`

```json
{
  "connected": true,
  "flying": false,
  "armed": false,
  "locked": false,
  "x": 0.0, "y": 0.0, "z": 0.0,
  "roll": 0.0, "pitch": 0.0, "yaw": 0.0,
  "battery_v": 3.92,
  "link_quality": 95.0,
  "last_error": null
}
```

### `POST /command`

请求体是一个 JSON 对象，`action` 必填：

| action | 参数 | 说明 |
|---|---|---|
| `takeoff` | `height` (m, 默认 0.3) | 缓升并悬停 |
| `land` | — | 受控降落，落地后切电机 |
| `hover` | — | 停住水平移动，保持高度 |
| `stop` | — | 立即切电机（空中会掉下） |
| `estop` | — | 紧急切电机（最高优先级，即时生效） |
| `move` | `vx` `vy` `vz` (m/s) `yawrate` (deg/s) `duration` (s) | 速度移动，需先起飞 |

示例：

```bash
curl -s -X POST http://127.0.0.1:18790/command \
  -H 'Content-Type: application/json' \
  -d '{"action":"takeoff","height":0.4}'

curl -s -X POST http://127.0.0.1:18790/command \
  -H 'Content-Type: application/json' \
  -d '{"action":"move","vx":0.3,"duration":1.5}'

curl -s -X POST http://127.0.0.1:18790/command \
  -H 'Content-Type: application/json' \
  -d '{"action":"land"}'
```

响应 `202` 表示已入队执行；随后用 `GET /status` 确认状态。`estop` 走
高优先级通道，即使正在执行长移动也会立即处理，并清空排队中的普通指令。

如果 `config.json` 里配置了 `command_server_token`，每次请求需带
`Authorization: Bearer <token>` 或 `?token=<token>`。

## OpenClaw 必须遵守的安全规则

1. **飞行前先 `status`**：确认 `connected=true`、`locked=false`、
   `battery_v >= 3.9`。任何一项不满足就停止操作并告知用户。
2. **`takeoff` 后逐小步移动**：`move` 的 `duration` 不超过 2 秒，
   每次移动后 `status` 确认位置和高度正常。
3. **结束必须 `land`**：确认 `flying=false` 后才算完成；不要直接退出。
4. **任何异常 → `estop`**：失控、倾斜过大、接近障碍物、通讯不稳时
   立即 `estop`（注意这是坠机式急停，仅紧急时用）。
5. **一个时刻只能有一个进程占用无线电**：操作前确认 bridge、
   `04_flying.py`、GUI 地面站没有同时在跑。
6. **不要连续多次 `takeoff`**：已在飞行时 `takeoff` 会被忽略，
   先 `land` 再起飞。
7. **`estop` 后会锁存**：急停后 `get_status` 的 `estop_latched=true`，
   takeoff/spin_test 会被拒绝；解锁只能由操作员在地面站 GUI 点击
   "解除锁存"或对无人机断电重启（掉线超过 10 秒后重连），agent 没有任何
   解锁接口，不要尝试解锁或反复起飞。

## 通过地面站 GUI 聊天面板操作（推荐）

地面站主窗口底部自带 OpenClaw 聊天面板，无需额外工具即可对话：

1. 确认 gateway 聊天端点已开启（`~/.openclaw/openclaw.json` 里
   `gateway.http.endpoints.chatCompletions.enabled=true`，然后重启
   gateway，见 README-zh.md 第五节）。
2. 把 `gateway.auth.token` 填到地面站 `config.json` 的 `openclaw.token`
   （config.json 已 gitignore，不会提交）。
3. 启动 `python main.py`，在底部聊天框输入指令，例如：
   - “检查无人机状态，能不能起飞”
   - “起飞到 0.4 米并悬停”
   - “前进 1 秒然后降落”
   - “立即急停”

地面站会把系统提示词（含接口用法和安全规则）和当前遥测快照一起发给
OpenClaw。OpenClaw 通过 `curl http://127.0.0.1:18790/...` 执行操作，
和 CLI/HTTP 两种方式等价。

注意：聊天面板里 OpenClaw 的每一次回复都会实时流式显示；如果它开始
执行长任务，可以用“停止”按钮中断请求（已发出的无人机指令不会回滚，
请根据实际情况用降落/急停收尾）。
