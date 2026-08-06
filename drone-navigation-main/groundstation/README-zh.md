# Crazyflie QT 地面站 · 完整使用手册

一份独立于网站（`client/`、`server/`、MediaMTX）的桌面地面站：直接通过
Crazyradio + cflib 控制 Crazyflie，直接读取 ESP32 摄像头画面，内置
OpenClaw 对话面板。本手册**从零开始**，不需要看仓库里其他文档。

> **给自动化 agent 使用**：每一节的末尾都提供了一段「建议提示词」（`txt`
> 代码块）。把对应步骤的提示词原样粘贴给自动化 agent（如 OpenClaw /
> Codex），它会按本手册执行该步骤；提示词里写明了要验证什么、报错怎么处理。

---

## 1. 硬件准备

| 物品 | 说明 |
|---|---|
| Crazyflie 2.x 无人机 | 电池已充电（起飞建议 ≥ 3.9 V，低于 3.7 V 会拒绝起飞） |
| Crazyradio PA 无线电棒 | 插在电脑 USB 口（VID 1915 / PID 7777） |
| ESP32-S3 摄像头（可选） | 焊在无人机上，提供视频画面 |
| USB 数据线 | 备用：读/写 EEPROM 身份时用 |

**无人机开机与自检**：装上电池开机。观察 LED：

- 蓝色 LED 常亮、绿灯常亮 → 自检完成，可连接
- 红灯一直闪 → 正在自检/异常，等它完成；若持续，拔电池重开
- 两个蓝灯 ~1 Hz 闪烁 → bootloader 模式（正常升级/配置时才会进入）
- 起飞后**LOCKED**：说明上次飞行异常断电，必须拔电池重启

> 建议提供给自动化 agent 的提示词：
```txt
请参照第 1 节核对硬件准备和无人机开机自检（电池电压、LED 状态），逐项告诉我结果。
```

---

## 2. 第一次配置（Windows + WSL 双端）

地面站跑在 WSL 里，但 USB 设备要先从 Windows 侧"借"给 WSL。

### 2.1 Windows：把无线电棒附加到 WSL

打开**管理员 PowerShell**，先看设备列表：

```powershell
usbipd list
```

找到 `Crazyradio PA USB Dongle`（VID 1915），记下它的 BUSID（例如 `1-13`）。
然后执行（BUSID 换成你的）：

```powershell
usbipd bind --force --busid 1-13   # 只需一次；如果报 hrdevmon 警告就加 --force
usbipd attach --wsl --busid 1-13   # 每次 WSL 重启 / 拔插无线电棒后要重跑
```

**常见错误**：

| 现象 | 处理 |
|---|---|
| `Device in error state` | 先 `usbipd detach --busid 1-13`，等 2 秒再 attach |
| `hrdevmon` 警告 | bind 时加 `--force` |
| attach 后 WSL 里还是看不到 | 拔插一次无线电棒，重复 detach → attach |

> 建议提供给自动化 agent 的提示词：
```txt
请参照 2.1 把 Crazyradio 附加到 WSL（usbipd list → bind --force → attach）,
完成后用 `lsusb | grep 1915` 验证并告诉我结果。不要做飞行操作。
```

### 2.2 WSL：确认设备 + 权限

在 WSL 终端确认设备出现了：

```bash
lsusb | grep 1915
# 应看到: Nordic Semiconductor ASA Bitcraze Crazyradio (PA) dongle
```

给设备读写权限（设备号以实际为准，`ls /dev/bus/usb/001/` 查看）：

```bash
sudo chmod 0666 /dev/bus/usb/001/00X
```

更省事的方式：创建 udev 规则，之后插上自动给权限：

```bash
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="1915", ATTR{idProduct}=="7777", MODE="0666"' | sudo tee /etc/udev/rules.d/99-crazyradio.rules
sudo udevadm control --reload && sudo udevadm trigger
```

> **重要**：一个 Crazyradio 同一时间只能被一个程序占用。运行地面站前，
> 停掉 `start_bridge.sh`、`motion_control_ws.py`、`01~05_*.py` 等程序。

> 建议提供给自动化 agent 的提示词：
```txt
请参照 2.2 确认 WSL 里 Crazyradio 可见并完成权限配置（udev 规则或 chmod），
同时确认没有其他程序占用无线电，完成后告诉我结果。
```

### 2.3 软件环境

地面站需要 `drone-navigation` conda 环境（含 cflib）和 PySide6：

```bash
conda activate drone-navigation
pip install cflib            # 环境里通常已有
pip install PySide6 -i https://pypi.tuna.tsinghua.edu.cn/simple
```

如果还没有这个 conda 环境：

```bash
conda create -n drone-navigation python=3.12 -y
conda activate drone-navigation
pip install cflib PySide6 -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> 建议提供给自动化 agent 的提示词：
```txt
请参照 2.3 准备 drone-navigation 环境（cflib + PySide6），
用 `python -c "import cflib, PySide6"` 验证后告诉我结果。
```

### 2.4 中文字体（防止界面中文变方块）

WSL 默认没有中文字体，界面中文会显示成方块。装一次：

```bash
sudo apt install -y fonts-noto-cjk
```

启动地面站时终端会打印 `界面字体: Noto Sans CJK SC` 表示生效。

> 建议提供给自动化 agent 的提示词：
```txt
请参照 2.4 安装中文字体，用 `fc-list | grep "Noto Sans CJK SC"` 验证后告诉我结果。
```

### 2.5 中文输入法（聊天/输入框输中文）(BUG)

Ubuntu 22.04 下 PySide6 自带 ibus 插件，装 ibus + 智能拼音即可：

```bash
sudo apt install -y ibus ibus-libpinyin
```

如果 `apt` 下载卡死，把 apt 源换成清华镜像（官方源在国内很慢）：

```bash
sudo cp /etc/apt/sources.list /etc/apt/sources.list.bak
sudo tee /etc/apt/sources.list > /dev/null <<'EOF'
deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ jammy main restricted universe multiverse
deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ jammy-updates main restricted universe multiverse
deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ jammy-backports main restricted universe multiverse
deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ jammy-security main restricted universe multiverse
EOF
sudo apt update
```

然后配置输入法环境变量（已写入 `~/.bashrc` 可跳过；`run_gui.sh`
会自动处理）：

```bash
export GTK_IM_MODULE=ibus
export QT_IM_MODULE=ibus
export XMODIFIERS=@im=ibus
eval "$(dbus-launch --sh-syntax)" && export DBUS_SESSION_BUS_ADDRESS
ibus-daemon -drx
gsettings set org.freedesktop.ibus.general preload-engines "['libpinyin', 'xkb:us::eng']"
```

**中英文切换**：libpinyin 默认用 **左 Shift** 切换中/英，打开就是中文
拼音模式。如果 Shift 没反应，右键 ibus 图标 → 首选项里检查切换键。

> 建议提供给自动化 agent 的提示词：
```txt
请参照 2.5 配置 ibus + 智能拼音（apt 卡死就换清华镜像），
配置后告诉我中英文切换键和验证方式。
```

---

## 3. 配置 config.json

首次运行前复制模板：

```bash
cd /mnt/c/Users/10206/Desktop/Session-2-202608/drone-navigation-main/groundstation
cp config.example.json config.json
```

`config.json` 关键字段（**已加入 .gitignore，不会提交**）：

```json
{
  "radio_uri": "radio://0/12/2M/8A3F5C2D9E",
  "camera_url": "http://10.219.80.107/stream",
  "command_server_host": "127.0.0.1",
  "command_server_port": 18790,
  "command_server_token": "",
  "takeoff_height": 0.3,
  "openclaw": {
    "base_url": "http://127.0.0.1:18789",
    "token": "openclaw-drone-navigation",
    "model": "openclaw/default",
    "user": "groundstation-gui",
    "system_prompt": "告诉 OpenClaw 如何操作地面站，见 OPENCLAW.md"
  }
}
```

> 建议提供给自动化 agent 的提示词：
```txt
请参照第 3 节生成并检查 config.json（radio_uri / camera_url / openclaw.token），
确认各字段已填当前值；不要修改或提交 config.json。
```

### 3.1 radio_uri（无线电身份）

`radio://<无线电棒编号>/<信道>/<速率>/<地址>`。出厂默认是
`radio://0/80/2M/E7E7E7E7E7`。**如果无人机 EEPROM 身份被改过，必须一致**，
否则连接超时（`Too many packets lost`）。

通过 USB 线读取当前身份：

```bash
cd /mnt/c/Users/10206/Desktop/Session-2-202608/drone-navigation-main/extension/crazyflie_bridge
python provision_drone.py --read-only
```

> 提示：USB 身份读取需要把无人机通过 USB 线连电脑（Windows 侧 attach 串口
> 设备后，WSL 里是 `usb://0`）。本机当前身份是
> `radio://0/12/2M/8A3F5C2D9E`，默认配置已填好。

> 建议提供给自动化 agent 的提示词：
```txt
请参照 3.1 读取无人机 EEPROM 身份并与 config.json 的 radio_uri 核对，
一致就通过；不一致先告诉我怎么改，等我确认。
```

### 3.2 camera_url（ESP32 摄像头）

摄像头 IP 每次连接热点可能变化。在 Windows 的热点管理页面找到名为
`espressif` 的设备，IP 例如 `10.219.80.107`，填到 `camera_url`。
摄像头连的是 2.4GHz 热点（手机热点名字如 `lclMagic6`）。IP 变了在 GUI
的视频地址框直接改，点"连接"即可。

> 建议提供给自动化 agent 的提示词：
```txt
请参照 3.2 找到 ESP32 摄像头的 IP 并核对 config.json 的 camera_url，
用 curl 验证视频流可达后告诉我结果。
```

---

## 4. 运行地面站（GUI）

```bash
cd /mnt/c/Users/10206/Desktop/Session-2-202608/drone-navigation-main/groundstation
conda activate drone-navigation
bash run_gui.sh          # 会自动启动 ibus 输入法并打开窗口
```

或直接 `python main.py`（需已配置好输入法环境变量）。

> 建议提供给自动化 agent 的提示词：
```txt
请参照第 4 节启动地面站 GUI（确认无线电已 attach、config.json 已配置），
告诉我窗口是否正常打开、聊天面板是否在线；报 libxcb 错误按第 7 节处理。
```

### 4.1 界面布局

| 区域 | 内容 |
|---|---|
| 左上 | ESP32 摄像头画面（地址可改，可翻转 180°） |
| 左下 | 位置轨迹俯视图（绿色十字=起飞点，绿线=轨迹，绿三角=当前位置） |
| 中上 | 姿态仪表：横滚弧形表 / 俯仰气泡条 / 航向罗盘 |
| 中 | 电池 / 高度 / 链路进度条 + 数字 |
| 右侧 | 飞行控制按钮 + 方向键 + 急停 |
| 底部 | OpenClaw 聊天面板 |

### 4.2 按键

| 按键 | 功能 |
|---|---|
| W / ↑ | 前进 |
| S / ↓ | 后退 |
| A / ← | 向左 |
| D / → | 向右 |
| Space | 上升 |
| Shift | 下降 |
| Q / E | 左转 / 右转 |
| T | 起飞（高度用右侧输入框） |
| L | 降落 |
| H | 悬停 |
| X | **急停**（立即切电机） |
| Esc | 停止（立即切电机） |

### 4.3 按钮含义

- **起飞**：缓升到设定高度（默认 0.3 m）并悬停
- **降落**：受控缓降，落地后自动切电机并解臂
- **悬停**：停住水平移动，保持当前高度
- **停止 / 急停（E-STOP）**：立即切断电机——**空中会直接掉下来**，
  优先用降落。急停走高优先级通道，即使正在执行长移动也会立即生效

> 建议提供给自动化 agent 的提示词：
```txt
请按 4.1–4.3 给我讲解界面布局、按键功能和按钮含义，
重点说明停止/急停与降落的区别。
```

### 4.4 旋翼慢速测试（起飞前必做）

每次飞行前检查桨叶和电机。GUI 里对 OpenClaw 说"逐个慢速转四个旋翼
做测试"，或命令行：

```bash
python cli.py spin-test --power 4000 --duration 2
```

无人机会按 m1 → m2 → m3 → m4 逐个慢转（约 6% 功率、每个 2 秒）。
测试时放平整桌面、装好桨叶，别拿在手里；随时可按 X 停。

> 建议提供给自动化 agent 的提示词：
```txt
请按 4.4 执行旋翼慢速测试（确认无人机放平、无线电无其他程序占用），
正常输出 spin_test done；异常按第 7 节排查，不要起飞。
```

---

## 5. OpenClaw 集成（聊天指挥无人机）

### 5.1 开启 gateway 聊天端点（只需一次）

OpenClaw 的 OpenAI 兼容接口**默认关闭**。编辑 `~/.openclaw/openclaw.json`，
在 `gateway` 下加：

```json
  "gateway": {
    "http": {
      "endpoints": {
        "chatCompletions": { "enabled": true }
      }
    }
  }
```

重启 gateway：

```bash
export PATH="$HOME/node-v22.23.2-linux-x64/bin:$PATH"
openclaw gateway stop
sleep 2
setsid nohup openclaw gateway --port 18789 > ~/openclaw.log 2>&1 < /dev/null &
```

验证：`curl -s http://127.0.0.1:18789/health` 应返回 `{"ok":true,"status":"live"}`。

> 建议提供给自动化 agent 的提示词：
```txt
请按 5.1 开启 gateway 聊天端点并重启 gateway，
用 `curl -s http://127.0.0.1:18789/health` 验证后告诉我结果。
```

### 5.2 配置 token 与对话

把 gateway token（`~/.openclaw/openclaw.json` 里 `gateway.auth.token`）填到
`config.json` 的 `openclaw.token`。启动 GUI 后底部聊天面板显示
`OpenClaw: 在线`，就可以直接对话：

- "检查无人机状态，能不能起飞"
- "起飞到 0.4 米并悬停"
- "逐个慢速转四个旋翼做测试"
- "前进 1 秒然后降落"
- "立即急停"

勾选"附带遥测"会把当前无人机快照发给 OpenClaw。回复实时流式显示；
如果它执行长任务，可用"停止"按钮中断。

> OpenClaw 的 main agent 首次使用会做初始化对话（可能问你要名字），
> 先在聊天面板里跟它聊完，之后就能正常指挥。

> 建议提供给自动化 agent 的提示词：
```txt
请按 5.2 把 gateway token 填到 config.json 的 openclaw.token，
启动 GUI 确认聊天面板“OpenClaw: 在线”，并向它发“检查无人机状态，能不能起飞”验证。
```

### 5.3 无界面模式（脚本/自动化）

完整接口见 [OPENCLAW.md](OPENCLAW.md)。快速示例：

```bash
python cli.py status                    # 查看连接/电池/锁定
python cli.py takeoff --height 0.4
python cli.py move --vx 0.3 --duration 1.5
python cli.py land
python cli.py estop
python cli.py serve                     # 长驻 HTTP 接口（默认 18790）
```

```bash
curl -s http://127.0.0.1:18790/status
curl -s -X POST http://127.0.0.1:18790/command \
  -H 'Content-Type: application/json' \
  -d '{"action":"takeoff","height":0.4}'
```

可用 action：`takeoff` `land` `hover` `stop` `estop` `move` `spin_test`。

> 建议提供给自动化 agent 的提示词：
```txt
请按 5.3 和 OPENCLAW.md 验证地面站接口（status / serve / POST command 格式），
没有我的允许不要真的执行 takeoff。
```

---

## 6. 安全规则（必读）

1. 电池 ≥ 3.9 V 再飞（< 3.7 V 地面站直接拒绝起飞）
2. 飞行前做旋翼慢速测试；桨叶无缺损、安装正确
3. 起飞前确认周围净空 ≥ 2 米、拔掉 USB 线、无人机不在 LOCKED 状态
4. 运动看门狗：0.5 秒没有新指令会自动回到悬停
5. **停止/急停会直接切断电机，空中会掉下来**——优先用降落
6. LOCKED 状态必须断电重启解锁
7. 一个时刻只有一个程序占用无线电
8. 空中急停是坠机式急停，仅紧急情况使用

> 建议提供给自动化 agent 的提示词：
```txt
请熟记第 6 节的安全规则，并在后续所有操作中遵守；起飞前先复述确认。
```

---

## 7. 故障排查大全

| 现象 | 原因 / 处理 |
|---|---|
| `Cannot find a Crazyradio Dongle` | 无线电棒没 attach：Windows 管理员执行 `usbipd attach --wsl --busid X`；再 `lsusb \| grep 1915` 确认 |
| attach 报 `Device in error state` | `usbipd detach --busid X` → 等 2 秒 → 重新 attach |
| 权限不足（open 失败） | `sudo chmod 0666 /dev/bus/usb/001/00X`（设备号以 `ls /dev/bus/usb/001/` 为准） |
| 连接超时 `Too many packets lost` | radio_uri 与无人机 EEPROM 身份不一致；或无人机没开机 |
| LOCKED 拒绝起飞 | 无人机断电重启 |
| 起飞报 `arming failed` | 先断电重启无人机等自检完成；检查有没有其他程序占用无线电（`pgrep -af python`） |
| 电机停不下来 | 立即按 X 急停；若断连，等待电池耗尽或拔无线电棒（看门狗会切电机） |
| 视频一直加载 | 摄像头热点是否连上；`camera_url` 的 IP 变了；勾选"画面翻转" |
| 中文显示方块 | `sudo apt install -y fonts-noto-cjk` 后重启 |
| 输入框无法输入中文 | 装 ibus + ibus-libpinyin（见 2.5），用 `bash run_gui.sh` 启动 |
| PySide6 报 libxcb 错误 | `sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-keysyms1` |
| 端口 18790 被占用 | `python cli.py serve --port 18791` 或在 config.json 改端口 |
| 聊天面板"未连接" | gateway 没在跑：`curl -s http://127.0.0.1:18789/health`；端点未开启见 5.1 |
| 聊天报 401 | `config.json` 的 `openclaw.token` 与 `~/.openclaw/openclaw.json` 的 `gateway.auth.token` 不一致 |
| apt 下载卡死 | 换清华镜像（见 2.5） |
| `motorPowerSet` 参数不存在 | 删除 `groundstation/cache/` 后重试 |

> 建议提供给自动化 agent 的提示词：
```txt
请把第 7 节的故障排查表作为排障手册，遇到问题时先对照定位，
给出最小改动方案，不要擅自改配置。
```

---

## 8. 目录结构

```
groundstation/
├── main.py                  # GUI 入口
├── cli.py                   # 无界面 CLI
├── run_gui.sh               # 一键启动（含输入法）
├── config.example.json      # 配置模板
├── config.json              # 本地配置（已 gitignore）
├── README-zh.md             # 本手册
├── OPENCLAW.md              # OpenClaw 操作接口详细说明
└── app/
    ├── config.py            # 配置加载
    ├── controller.py        # 核心：连接/遥测/飞行/急停/旋翼测试
    ├── command_server.py    # 本地 HTTP JSON API
    ├── openclaw_client.py   # OpenClaw 聊天客户端（SSE）
    ├── video.py             # ESP32 MJPEG 拉流
    └── ui/                  # PySide6 界面
```

> 建议提供给自动化 agent 的提示词：
```txt
请按第 8 节给我说明 groundstation 各文件/模块的职责，
并标注哪些可改、哪些是运行产物或含敏感信息（如 config.json）。
```
