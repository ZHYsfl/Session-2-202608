# Crazyflie 开发环境（版本基线见 introduction.md「环境版本基线」小节）
#
# 构建：
#   docker build -t crazyflie-env:2026.04 .
#
# 运行（挂载 Crazyradio USB + 图形界面转发，Linux 主机）：
#   xhost +local:docker
#   docker run -it --rm \
#     --device=/dev/bus/usb \
#     -e DISPLAY=$DISPLAY \
#     -v /tmp/.X11-unix:/tmp/.X11-unix \
#     crazyflie-env:2026.04
#
# 容器内：
#   - Python 虚拟环境（uv 管理，Python 3.12，已装 cflib/cfclient）已自动激活
#   - cfclient：直接运行 `python -m cfclient.gui`（需图形转发）
#   - 固件源码在 /opt/crazyflie-firmware（已 checkout 2026.04 并预编译验证）
#   - ESP-IDF v5.5.5 在 /opt/esp-idf，每个 shell 已自动 source export.sh

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# ---- 系统依赖 ----
# ESP-IDF 官方前置依赖 + cfclient(PyQt6) 图形库 + 固件编译工具链
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl wget ca-certificates xz-utils unzip \
    build-essential cmake ninja-build ccache \
    flex bison gperf \
    python3 python3-pip python3-venv \
    libffi-dev libssl-dev dfu-util libusb-1.0-0 usbutils udev \
    gcc-arm-none-eabi binutils-arm-none-eabi libnewlib-arm-none-eabi \
    libgl1 libegl1 libxkbcommon0 libdbus-1-3 libfontconfig1 libxcb-cursor0 \
    && rm -rf /var/lib/apt/lists/*

# ---- uv + Python 3.12 虚拟环境 ----
COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /uvx /usr/local/bin/
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN uv venv --python 3.12 /opt/venv \
    && uv pip install --python /opt/venv/bin/python \
       cflib==0.1.32 cfclient==2026.4

# ---- Crazyflie 固件 2026.04（克隆、子模块、预编译验证） ----
RUN git clone https://github.com/bitcraze/crazyflie-firmware.git /opt/crazyflie-firmware \
    && cd /opt/crazyflie-firmware \
    && git checkout 2026.04 \
    && git submodule update --init --recursive \
    && make defconfig \
    && make -j"$(nproc)"

# ---- ESP-IDF v5.5.5 ----
ENV IDF_PATH=/opt/esp-idf
RUN git clone -b v5.5.5 --depth 1 --shallow-submodules --recursive \
      https://github.com/espressif/esp-idf.git /opt/esp-idf \
    && cd /opt/esp-idf \
    && ./install.sh esp32

# 每个交互 shell 自动激活 ESP-IDF 环境（venv 已通过 ENV PATH 生效）
RUN echo '. /opt/esp-idf/export.sh >/dev/null 2>&1' >> /etc/bash.bashrc

# ---- 追加 Python 依赖（放在最后：改 requirements.txt 只重建这一层） ----
# 后续课程（VLA 模型、MARL 等）需要新依赖时，编辑 requirements.txt 后重新
# docker build 即可，上面所有重层都会命中缓存。
COPY requirements.txt /tmp/requirements.txt
RUN uv pip install --python /opt/venv/bin/python -r /tmp/requirements.txt

WORKDIR /work
CMD ["/bin/bash"]
