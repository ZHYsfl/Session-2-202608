# 实机操作手册：PC 开机 → 控制 Crazyflie 无人机

> 适用环境：Windows 10/11 + WSL2（Ubuntu 22.04），本项目本地开发栈。
> 本手册按“从零开机到飞起来”的顺序编写，照着做即可。

---

## 0. 本机环境速览（重要）

| 组件 | 位置 / 命令 |
| --- | --- |
| WSL 用户 | `serral` |
| Node.js | `~/node-v22.23.2-linux-x64`（已写入 `~/.bashrc` PATH） |
| conda | `~/miniconda3`，环境：`pg`（PostgreSQL）、`drone-navigation`（后端/无人机）、`synapse` |
| 运行代码副本 | `~/drone-navigation`（WSL 内，README 要求不要放 /mnt/c） |
| 开发/提交代码 | `C:\Users\10206\Desktop\Session-2-202608\drone-navigation-main`（git 006 分支） |
| 前端开发服务器 | 从 `/mnt/c/Users/10206/Desktop/Session-2-202608/drone-navigation-main/client` 启动 |
| ESP32-S3 摄像头 | 只连热点 `lclMagic6` / `li20061114`（2.4GHz），默认地址见 3.1 节 |

> 注意：bridge、后端、Synapse 等**运行**用的都是 `~/drone-navigation` 这份副本；
> 如果改了 `/mnt/c` 仓库里的代码，记得同步到 `~/drone-navigation` 再重启对应服务。

---

## 1. 开机后：启动整套服务（WSL 终端，一次跑完）

打开 **WSL（Ubuntu）终端**，粘贴执行：

```bash
export PATH="$HOME/node-v22.23.2-linux-x64/bin:$PATH"

# ① PostgreSQL（端口 5433）
~/miniconda3/envs/pg/bin/pg_ctl -D ~/pgdata -l ~/pgdata.log start

# ② FastAPI 后端（端口 8000）
cd ~/drone-navigation/server
setsid nohup ~/miniconda3/envs/drone-navigation/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > ~/uvicorn.log 2>&1 < /dev/null &

# ③ MediaMTX（HLS 8888 / WebRTC 8889 / API 9997）
cd ~/mediamtx_v1.9.0
setsid nohup ./mediamtx > ~/mediamtx.log 2>&1 < /dev/null &

# ④ Synapse（端口 8008）
setsid nohup ~/miniconda3/envs/synapse/bin/python -m synapse.app.homeserver -c ~/synapse-data/homeserver.yaml > ~/synapse.log 2>&1 < /dev/null &

# ⑤ OpenClaw 网关（端口 18789）
setsid nohup openclaw gateway --port 18789 > ~/openclaw.log 2>&1 < /dev/null &

# ⑥ 前端（端口 5173，从 Windows 仓库目录启动）
cd /mnt/c/Users/10206/Desktop/Session-2-202608/drone-navigation-main/client
setsid nohup npm run dev > ~/vite.log 2>&1 < /dev/null &
```

启动后自检：

```bash
curl -s http://localhost:8000/api/health        # 期望 {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:5173/   # 期望 200
```

Windows 浏览器打开 `http://localhost:5173` 确认前端可访问。

> 如果某条命令提示“服务已在运行”（如 pg_ctl），忽略即可。

---

## 2. 接入无线电（Crazyradio PA）

### 2.1 Windows 侧（管理员 PowerShell）

每次**重新插拔电台或重启 WSL 后**都要执行：

```powershell
usbipd list                        # 确认 1-13 行存在（Crazyradio PA USB Dongle）
usbipd attach --wsl --busid 1-13   # 每次重新插拔电台 / 重启 WSL 后都要执行
```

> `usbipd bind` 只需做过一次（已持久化）；`attach` 每次都要做。

> 注意：`attach` 后设备状态应显示 **Attached**。如果显示的是 **Shared (forced)**，说明 attach 掉了，重跑上面的 attach 即可（视频/无线电失灵时先查这一行）。

### 2.2 WSL 侧确认

```bash
lsusb | grep 1915                  # 应看到 Nordic Semiconductor Crazyradio
DEV=$(lsusb | grep '1915:7777' | awk '{print "/dev/bus/usb/"$2"/"$4}' | tr -d ':')
ls -l "$DEV"                       # 权限应为 crw-rw-rw-（设备号会变，自动查找）
```

如果权限不是 `rw-rw-rw-`：

```bash
sudo chmod 0666 "$DEV"
```

如果 `ls -l /dev/bus/usb/...` 报 **Permission denied**，或 cflib 报 **The device has no langid**，
通常是 `/dev/bus/usb` 目录丢了执行位（权限变成 `drw-rw-rw-`），先补上再赋权：

```bash
sudo chmod 755 /dev/bus/usb
sudo chmod 0666 "$DEV"
```

（设备节点号每次重插都会变，永远用上面的 `lsusb` 自动查找，不要写死节点号。）

---

## 3. 无人机准备

1. 电池充满电（**≥ 4.1V 再飞**，`01_connect.py` 会显示电压）
2. 平放在开阔桌面上，按电源按钮开机（蓝灯亮）
3. **每次飞行前**检查螺旋桨：

```bash
conda activate drone-navigation
cd ~/drone-navigation/extension/simple_crazyflie
python 03_propellers.py            # 每个桨单独转 + 20cm 短悬停
```

---

## 3.1 ESP32-S3 摄像头（画面来源，重要）

摄像头是 ESP32-S3（固件 `esp32s3_eye_ov2640_stream`，OV2640，输出 `/stream` MJPEG）。
它的 WiFi 配置**烧死在固件里**：只会连 **`lclMagic6` / `li20061114`（仅 2.4GHz）**。
所以每次使用都要让"摄像头 + 电脑"处于同一个网络：

### 步骤

1. **手机开热点**（Android 可直接自定义；iPhone 需先把手机改名）：
   - 热点名称：`lclMagic6`（一字不差，区分大小写）
   - 密码：`li20061114`
   - 频段：**2.4GHz**（ESP32 不支持 5GHz）
2. **电脑也连这个热点**（Crazyradio 是 USB 的，不受影响）
3. 摄像头通电开机 → 自动连上热点，从手机热点的已连接设备里找它的 IP
   （设备名显示为 `espressif`，本次为 `10.219.80.107`，下次可能变）
4. 验证画面地址：浏览器打开 `http://<摄像头IP>/stream` 能看到实时画面即正常

> 摄像头默认**连不到任何别的 WiFi**（酒店/手机热点/实验室网络都不行，除非 SSID 正好叫
> `lclMagic6`）。想让它改连别的网络，需要重新烧固件，见 8.3 节。

---

## 4. 启动 bridge（无人机 ↔ 网页的桥梁）

在 WSL 终端：

```bash
conda activate drone-navigation
cd ~/drone-navigation/extension/crazyflie_bridge

# CRAZYFLIE_IP 必须填摄像头 IP（见 3.1）。注意：这行行尾不要加任何注释，
# 行内注释会把整条命令搞坏（报 ": command not found"），环境变量就没传进去。
CRAZYFLIE_IP="10.219.80.107" \
RADIO_URL="radio://0/12/2M/8A3F5C2D9E" \
TELEMETRY_SERVER="ws://127.0.0.1:8000/api/drone/telemetry/publish" \
MEDIAMTX_URL="http://[::1]:8889" MEDIAMTX_API="http://localhost:9997" \
./start_bridge.sh
```

- 台架演练（不飞行）：命令前加 `CF_NO_FLY=1 \`
- 多机/改过身份：把 `RADIO_URL` 换成实际信道/地址（本机当前身份：`radio://0/12/2M/8A3F5C2D9E`）
- 没有摄像头 / 不想看画面：删掉 `CRAZYFLIE_IP` 行，`[Proxy] Stream error` 日志可忽略，不影响飞行
- 停止 bridge：`Ctrl+C`（会自动先降落再退出）

确认日志出现：

```
[Proxy] Connected to upstream: http://10.219.80.107/stream
[Bridge] Crazyflie connected: radio://0/12/2M/8A3F5C2D9E
[Bridge] Ready. Waiting for takeoff command...
[LIVE] STREAM LIVE. Stream ID: 'crazyflie-drone'
```

> ⚠️ **只允许一个 bridge 在跑**。再开一个会报 `Address already in use`（8082 被占）
> 或 `Too many packets lost`（无线电被占用）。重复运行前先清理：
> `pkill -9 -f "start_bridge|video_stream_proxy|telemetry_relay|motion_control_ws|crazyflie_mediamtx"`

> 如果日志报 **`Cannot find a Crazyradio Dongle`**：无线电的 usbipd attach 掉了
> （`usbipd list` 里显示 **Shared (forced)** 而不是 **Attached**），按第 2 节重新 attach 即可。
> 用 `lsusb | grep 1915` 确认 WSL 里能看到它，再赋权限。

> 如果日志出现 `[Bridge] Drone connection clean.` 然后退出，说明无人机端掉电/重启了——
> 检查无人机 LED 和电池，重启无人机电源后重跑。

---

## 5. 网页操控

Windows 浏览器打开 **`http://localhost:5173`** → 左侧菜单进入 **Real Drone** 页面。

HUD 应显示：

- 链路：在线（约 20 Hz）
- 位置 / 方向（姿态）/ 电池电压
- 画面：Real Drone 页面应有摄像头实时画面（已做垂直翻转，画面是正的）

### 按钮功能（务必分清）

| 按钮 | 行为 |
| --- | --- |
| 起飞（Takeoff） | 受控爬升到约 0.5m |
| 停止（⏹，切换按钮中间档） | **悬停**（速度归零，不会掉） |
| 降落（Landing） | 柔和受控降落到底 |
| **红色急停（estop，侧栏最顶部）** | **立即停桨，会自由落体**，仅失控时使用 |

飞行圆盘：推杆控制前后左右，旁边圆盘控制高度；松开即悬停。

### 飞行流程

1. 起飞前确认：电池 ≥3.9V、四周 ≥2m 净空、无人员宠物、桨已检查
2. 点 **Takeoff** → 无人机爬升悬停
3. 用圆盘操控，随时可点 ⏹ **停止**（悬停）
4. 结束 → 点 **Landing** 降落
5. 降落完成后 `Ctrl+C` 停 bridge，关无人机电源

---

## 6. 关机 / 停止顺序

```bash
# 1) 网页先 Landing 降落，然后 Ctrl+C 停 bridge
# 2) 关闭无人机电源开关

# 3) 停止各服务（按需）
pkill -f "uvicorn app.main:app"
pkill -f "mediamtx"
pkill -f "synapse.app.homeserver"
pkill -f "openclaw-gateway"
pkill -f "node .*vite"
~/miniconda3/envs/pg/bin/pg_ctl -D ~/pgdata stop
```

（可选）Windows 摄像头推流停止：`Stop-Process -Name python`。

---

## 7. 常见问题速查

| 现象 | 处理 |
| --- | --- |
| `Cannot find a Crazyradio Dongle` | attach 掉了（usbipd 显示 Shared 而非 Attached）→ 重跑 `usbipd attach --wsl --busid 1-13` + `chmod 0666` |
| 扫描报 `Resource busy` | 无线电正被 bridge/其他程序占用，先停掉再试 |
| 连接超时 `Too many packets lost` | 无人机没开机 / URI 不对 / 无线干扰 |
| `Battery: 0.00 V` | 参数读取竞争，重跑一次即可 |
| 电池 <3.9V | 先充电，不要飞 |
| 网页没画面 | ① 热点没开 / 摄像头没连上（看 3.1）；② `CRAZYFLIE_IP` 没写或写错；③ bridge 没重启 |
| bridge 报 `Address already in use` | 有另一个 bridge 在跑，`pkill` 清掉再启动 |
| bridge 报 `Too many packets lost` 且立刻退出 | 无线电被别的进程占用（或无人机没开机） |
| 改了前端代码页面没变化 | `/mnt/c` 下 Vite 常监听不到文件变化，重启 vite：`pkill -f vite` 后重跑第 1 节 ⑥ |
| 画面倒着/镜像 | 前端已对 `crazyflie-drone` 流做 `scaleY(-1)`；如仍不对，改 `RealDroneView.vue` 的 `.video--flip` |
| 按“停止”飞机下落 | 先确认不是顶部红色急停；若是切换按钮的 ⏹ 仍下落，抓 bridge 日志（Traceback / EMERGENCY STOP / Landing）发给我 |
| 网页打不开 5173 | 前端没启动，重跑第 1 节 ⑥ |
| 后端 /api/health 不通 | 后端没启动或 PostgreSQL 没起来 |

---

## 8. 第一次上手的四步验证（simple_crazyflie）

```bash
conda activate drone-navigation
cd ~/drone-navigation/extension/simple_crazyflie
python 01_connect.py      # 链路 + 电压
python 02_telemetry.py    # 拿起倾斜看姿态变化
python 03_propellers.py   # 每次飞行前检查桨
python 04_flying.py       # 首次试飞：0.3m 悬停
```

---

## 8.1 修改无人机无线电身份（EEPROM，多机防串扰）

多架无人机共处一室时必须给每架分配不同身份，否则同信道同地址会互相抢控。
项目规则：team N → 信道 2N、地址 `E7E7E7E7NN`（`provision_drone.py` 内置，团队号 1–13）。

```bash
conda activate drone-navigation
cd ~/drone-navigation/extension/crazyflie_bridge

python provision_drone.py --read-only          # 只读当前身份（走 USB）
python provision_drone.py --team 3 --yes       # 写入 team 3 身份：ch6 / E7E7E7E703 / 2M
```

要点：

- **走 USB**：先按第 2 节方式把无人机 USB 线挂进 WSL（VID 0483:5740）并赋权限；
  适合在室内用数据线连接时操作
- **走无线电**（户外/不想接线）：用 `--uri` 指定当前身份即可，无需 USB：

  ```bash
  # 先用当前身份连上无人机（写入前必须停掉 bridge，否则无线电被占用）
  python provision_drone.py --channel 12 --address 8A3F5C2D9E --datarate 2M \
      --uri radio://0/80/2M/E7E7E7E7E7 --yes
  ```

- 写入后脚本提示断电重启，再无线验证；验证用 `--verify-only --team 3`
- 改完身份后，bridge 的 `RADIO_URL` 也要改成实际身份（本机当前：`radio://0/12/2M/8A3F5C2D9E`）
- **只有主固件运行（无人机正常开机）时 USB 才可见**；bootloader 模式不枚举 USB（见下）

---

## 8.2 Bootloader 模式（刷固件用，日常用不到）

- 进入：关机状态下**按住电源键约 3 秒**，直到蓝色 LED 以约 1 Hz 闪烁
- 如果按 3 秒没反应：拔电池 → 按住电源键 → 插电池 → 继续按住约 3 秒
- **bootloader 模式不枚举 USB**（CF2 的 bootloader 只走无线电，官方文档确认），
  所以 Windows/WSL 里看不到它是正常现象，不是线坏了
- 该模式下刷固件走 Crazyradio（冷启动扫描信道 110/0），日常改 EEPROM 用不到它
- 无人机"一连就崩/重启"通常是**电池或电源线接触不良**（官方对 keeps resetting
  的标准答复）：检查电池 2P 线（Molex 51005）是否虚接，必要时重新插紧或换线

---

## 8.3 改摄像头 WiFi 配置（只有换网络时才需要）

摄像头 WiFi 配置是**编译在固件里的字符串**（当前值：`lclMagic6` / `li20061114`，
之前是 `HUAWEI-yang` / `justinlee`）。**NVS 里也有一份，但每次开机固件都会用
硬编码值覆盖回去，所以只改 NVS 没用，必须改固件二进制。**
方法是：替换二进制里的字符串 → 重算镜像校验和 + SHA-256 → esptool 刷回。

步骤（Windows 下，摄像头用 4pin-USB 线连电脑，显示为 COM 口，VID 303a:1001）：

```powershell
py -m pip install esptool
py -m esptool --chip esp32s3 --port COM13 chip_id      # 确认能连上
py -m esptool --chip esp32s3 --port COM13 read_flash 0x10000 0x100000 app.bin  # 备份应用分区（1MB）
```

修改要点：

- 在 `app.bin` 里搜旧的 SSID/密码字符串（本机旧值在 `0x5ca4` / `0x5cb0`，就在
  `esp_wifi_set_config` 附近），用新值替换；新值必须**不更长**，末尾补 `\0`
- 镜像头第 23 字节是 `hash_appended`（本机为 1，表示有追加 SHA-256），**不要动它**
- 校验和算法（ESP-IDF 官方）：所有段数据按 32 位小端字 XOR，初始 `0xEF`，得到
  32 位值后 4 个字节互相 XOR 得到校验字节；它存在**镜像末尾 16 字节对齐块的
  最后一个字节**（不是镜像头里）
- SHA-256 覆盖"镜像全部内容 + 校验字节"，存在校验字节之后的 32 字节；改完必须重算
- 用 `py -m esptool --chip esp32s3 --port COM13 write_flash 0x10000 app_patched.bin` 刷回，
  再断电重启摄像头

**日常使用建议保持 3.1 节的热点方案，不要随便刷**——刷错会开不了机（重新刷回备份即可，
改固件前一定先备份 `app.bin`）。
