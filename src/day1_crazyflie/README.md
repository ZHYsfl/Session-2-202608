# Day-1：Crazyflie 无人机开发与调试（工号 002，分支 002）

对应《introduction/introduction.md》第一天课题。代码放在 `src/day1_crazyflie/`。

## 评分对照

| 技能 | 分数 | 本目录对应实现 | 状态 |
|------|------|----------------|------|
| 基础 | 60 | 环境已装好；`01_connect_test.py`（连接）；`02_telemetry.py`（接收高度/速度/方向）；`03_takeoff_hover_land.py`（起飞/悬停≥10s/降落） | 代码✅，真机验证待硬件 |
| 进阶 | 80 | `04_flight_mission.py`（虚拟围栏内：起飞降落、前进后退、升降、转弯、加减速） | 代码✅ + 仿真✅，真机待硬件 |
| 卓越 | 100 | ESP-IDF 安装步骤见下方第 7 节（加摄像头 + Wi-Fi 模组回传视频） | 待硬件 |

## 环境版本基线（与 introduction.md 第 4 节对齐，2026-08-04）

| 组件 | 基线 | 本机状态 |
|------|------|----------|
| Python | 3.12（venv 隔离） | ✅ 3.12.10，venv 在 `.venv/` |
| cflib | 0.1.32 | ✅ 已装进 venv |
| cfclient | 2026.04 | ✅ 2026.4 已装进 venv |
| crazyflie-firmware | 2026.04 | 待真机烧录（第 C 节） |
| ESP-IDF | v5.5.5（LTS） | 安装中/待手工（第 7 节） |

## 已完成（自动）

- ✅ 安装 Python 3.12.10，并在 `.venv/` 建好隔离环境
- ✅ venv 内安装 `cflib==0.1.32`、`cfclient==2026.4`（与官方固件 `2026.04` 配套）
- ✅ 编写全部飞行/遥测脚本，并用**仿真模式**（`--dry`）验证逻辑
- ✅ 轨迹 CSV 记录 + 画图脚本

> 所有命令请先用 venv 的解释器：`.venv\Scripts\python.exe`（下文简称 `pyvenv`）。

## 目录结构

```
src/day1_crazyflie/
├── README.md
├── requirements.txt
├── cf_utils.py              # 公共：扫描/连接/URI
├── telemetry.py             # 遥测订阅（高度/速度/方向/电压）
├── virtual_fence.py         # 虚拟围栏 + 位置积分器 + 越界看门狗
├── sim.py                   # 仿真 MotionCommander（无硬件测试用）
├── 01_connect_test.py       # 连接测试
├── 02_telemetry.py          # 实时遥测 + CSV
├── 03_takeoff_hover_land.py # 起飞/悬停/降落（基础60）
├── 04_flight_mission.py     # 虚拟围栏飞行任务（进阶80）
├── 05_plot_trajectory.py    # 轨迹画图
└── cache/                   # cflib 参数/日志缓存（自动生成，已 gitignore）
```

## 用法（全部命令在 `src/day1_crazyflie/` 下执行）

```powershell
# 首次：安装依赖（venv 已建好）
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 0) 无硬件事先仿真验证（推荐先跑一遍）：
.venv\Scripts\python.exe 04_flight_mission.py --dry --csv mission_dry.csv
.venv\Scripts\python.exe 05_plot_trajectory.py mission_dry.csv mission_dry.png

# 1) 连接测试（需 Crazyradio + 无人机开机）
.venv\Scripts\python.exe 01_connect_test.py

# 2) 实时遥测 10 秒（接收高度/速度/方向/电压）
.venv\Scripts\python.exe 02_telemetry.py --seconds 10 --csv telemetry.csv

# 3) 起飞 → 悬停 10s → 降落（基础 60）
.venv\Scripts\python.exe 03_takeoff_hover_land.py --hover 10 --height 0.5

# 4) 虚拟围栏飞行任务（进阶 80，默认 2m x 2m x 1.2m 围栏）
.venv\Scripts\python.exe 04_flight_mission.py --csv mission.csv
#    已装 Flow deck 时用实测位置：
.venv\Scripts\python.exe 04_flight_mission.py --flow --csv mission.csv
```

> 也可以先 `.venv\Scripts\Activate.ps1` 激活环境，之后直接 `python xxx.py`。

- 默认 URI `radio://0/80/2M/E7E7E7E7E7`，可改环境变量 `CRAZYFLIE_URI` 或命令行 `--uri`。
- 每个脚本都带 `--dry` 仿真模式，**没有硬件也能先看一遍完整流程**。

---

## 需要你手工做的部分（我在这里暂停）

以下步骤必须有真机才能继续，**请逐项做完后再回来**：

### A. 硬件拆装（熟悉结构）
1. 拆下 Crazyflie 的桨叶保护罩与电池，观察飞控板（STM32 主控 + nRF51 无线 + 9 轴 IMU）、四个无刷电机与桨叶、电源管理模块。
2. 装回电池，注意电池线极性（红正黑负），**先装电池再插 Crazyradio，防止上电打火**。
3. 若后续要稳定悬停，计划加装 **Flow Deck v2**（光流 + 高度传感器）。

### B. 安装 Crazyradio USB 驱动（Zadig）
1. 把 Crazyradio USB 接收器插到电脑。
2. 下载 [Zadig](https://zadig.akeo.ie/)，用管理员身份运行。
3. 菜单 **Options → List All Devices**，选中 Crazyradio。
4. Target Driver 选 **libusb-win32**（或 WinUSB），点 **Install Driver**。
5. 插上无人机（开机，LED 闪烁）。此时运行 `python 01_connect_test.py` 应能扫描到。

> 若 `scan_uris()` 返回空：驱动没装对，或无人机没开机，或信道/地址不对。

### C. 固件烧录（预编译固件，无需自建工具链）
cfclient 图形界面最省事：
1. 命令行输入 `cfclient` 启动。
2. 菜单 **Connect → Bootloader**。
3. **From file** 标签：选官方预编译包 `crazyflie-firmware-2026.04.zip`
   （从 [bitcraze/crazyflie-firmware Releases](https://github.com/bitcraze/crazyflie-firmware/releases) 下载，平台选 `cf2`）。
   > 本机访问 GitHub 若被墙，可在 cfclient 的 **From release** 标签在线拉取，或挂代理下载后选 From file。
4. 选中无人机（DFU 模式，插入 USB 或长按电源键进 DFU），点 **Flash**。
5. 刷完重新开机，`01_connect_test.py` 能读到固件参数即成功。

> 想自己编译固件（课题描述第 3 步"编译"）需要 ARM 工具链 + make，Windows 上建议在
> **WSL2** 里：`sudo apt install gcc-arm-none-eabi build-essential`，然后
> `git clone https://github.com/bitcraze/crazyflie-firmware && cd crazyflie-firmware && make`。
> 预编译包流程已满足验收"烧录基础固件"，自编译属于加分项。

### D. 基础悬停验收（60 分）
1. 找开阔、无风、地面平整的空间，无人机周围留 1m 以上。
2. `python 03_takeoff_hover_land.py --hover 12 --height 0.5`。
3. 观察：能否稳定悬停 ≥10s、无明显漂移。**若漂移明显 → 必须加装 Flow Deck v2**（纯 IMU 无法钉住）。

### E. 进阶飞行验收（80 分）
1. 确认虚拟围栏尺寸（默认 2m×2m×1.2m）与你的飞行场地匹配，必要时 `--fence 宽,深,高`。
2. `python 04_flight_mission.py --csv mission.csv`（全程旁观，保持手在急停按钮/遥控旁）。
3. 完成后 `python 05_plot_trajectory.py mission.csv mission.png`，把图存到
   `summary/002/day-1-pics/` 供日结使用。

---

## 7. 卓越技能（100 分）：ESP-IDF + 摄像头 + Wi-Fi 视频回传（规划）

分三步，前两步需要硬件选型后再做：

1. **安装 ESP-IDF v5.5.5**（软件，当前正在装）：
   - 版本：**v5.5.5**（v5.5 分支为 LTS，支持至 2028-01，社区示例多基于 v5.x）。
   - 安装方式（git + 官方脚本，已在本机执行）：
     ```powershell
     git clone -b v5.5.5 --recursive --depth 1 https://github.com/espressif/esp-idf.git C:\Users\lenovo\esp\esp-idf
     cd C:\Users\lenovo\esp\esp-idf
     .\install.ps1            # 下载编译工具链到 ~\.espressif（需几分钟）
     .\export.ps1             # 设置 IDF_PATH 等环境变量
     idf.py --version         # 验证
     ```
   - 备选：图形化**离线安装器**见
     [Espressif 文档](https://docs.espressif.com/projects/esp-idf/zh_CN/latest/esp32/get-started/windows-setup.html)。
2. **硬件**：Crazyflie 上加装 **AI-deck**（内置 nRF52840 + ESP32 + 摄像头），
   或用外接 ESP32-CAM 摄像头模组接 Crazyflie 的扩展口。
3. **软件**：在 ESP-IDF 里写一个 `mjpeg_streamer` 例程，把摄像头 JPEG 帧经
   Wi-Fi 推流；电脑用 `ffplay`/浏览器打开 `http://<esp32-ip>:port/stream` 看实时画面。
   - 这需要把 Crazyflie 的串口/SPI 视频信号接出来——属于后续专项，先装好 ESP-IDF 即可。

---

## 排错 FAQ

| 现象 | 原因/解决 |
|------|-----------|
| `scan_uris()` 为空 | Crazyradio 驱动没装（Zadig 重装 libusb-win32）；无人机未开机 |
| 连接超时 | URI 信道/地址不对；换 1M 模式 `radio://0/80/1M/E7E7E7E7E7` |
| 悬停漂移大 | 无 Flow deck。加装 Flow Deck v2 并用 `--flow` |
| 飞行中突然下降 | 电量不足，`pm.vbat` 低于 3.4V 就降 |
| 刷固件失败 | 未进 DFU 模式；驱动是 USB 的而不是 radio 的 |

## 安全

- 无人机**必须有保护罩**，至少两人在场，一人操作一人监护。
- 任何异常立即拔电池（这是终极急停）。
- 首次飞行高度不超过 1m，围栏内活动。
