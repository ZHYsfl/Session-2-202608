#!/usr/bin/env python3
"""OpenClaw 主模型切换工具：deepseek-v4-flash / 微调 2B / 未微调 2B。

在 WSL 中运行（conda 环境自带 python3）：
    python3 tools/switch_model.py                   # 交互菜单，键入 1/2/3
    python3 tools/switch_model.py 1                 # 1 = deepseek-v4-flash
    python3 tools/switch_model.py 2                 # 2 = 微调 qwen3.5-2b-sft (:6006, thinking=low)
    python3 tools/switch_model.py 3                 # 3 = 未微调 qwen3.5-2b   (:6008, thinking=low)
    python3 tools/switch_model.py 2 --thinking medium   # 临时指定 thinking 档位
    python3 tools/switch_model.py 2 --keep-context       # 切换但保留旧会话上下文
    python3 tools/switch_model.py 2 --no-notify          # 切换后不发微信重置通知
    python3 tools/switch_model.py flash|sft|base    # 也可以用名字
    python3 tools/switch_model.py show               # 查看当前模型与连通性
    python3 tools/switch_model.py list               # 列出可选模型
    python3 tools/switch_model.py 2 --no-restart     # 只改配置不重启网关
    python3 tools/switch_model.py 2 --base-url http://127.0.0.1:6006 --force

注意：vLLM 隧道如果建在 Windows 侧（AutoDL 工具），WSL 里的 OpenClaw 网关
访问不到 Windows 的 127.0.0.1。请在 WSL 里再建一条隧道：
    ssh -N -L 6006:127.0.0.1:6006 -L 6008:127.0.0.1:6008 \
        root@connect.nmb2.seetacloud.com -p 35547
脚本会在切换前检查 vLLM 可达性，不可达时默认中止（加 --force 可强制切换）。
切换模型时**默认强制清空旧会话上下文**（旧会话移到备份目录，可恢复），
用 --keep-context 可跳过；切换后默认向微信发送一条"会话已重置"通知，
用 --no-notify 可跳过。微信 App 聊天窗口的历史记录只能手动删除
（长按会话 → 删除聊天记录），机器人无法代删。
"""

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import urllib.request

HOME = pathlib.Path.home()
CONFIG = HOME / ".openclaw" / "openclaw.json"
OPENCLAW_BIN = HOME / "node-v22.23.2-linux-x64" / "bin" / "openclaw"
GATEWAY_PORT = 18789
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

TARGETS = {
    "flash": {
        "label": "deepseek-v4-flash（云端 API，thinking=medium）",
        "primary": "deepseek/deepseek-v4-flash",
        "thinking": "medium",
    },
    "sft": {
        "label": "qwen3.5-2b-sft（本地 vLLM，蒸馏后，thinking=low）",
        "primary": "local-vllm/qwen3.5-2b-sft",
        "provider": "local-vllm",
        "model_id": "qwen3.5-2b-sft",
        "base_url": "http://127.0.0.1:6006",
        "context_window": 262144,
        "max_tokens": 8192,
        "thinking": "low",
    },
    "base": {
        "label": "qwen3.5-2b（本地 vLLM 原模型 :6008，未微调，thinking=low）",
        "primary": "local-vllm-base/qwen3.5-2b",
        "provider": "local-vllm-base",
        "model_id": "qwen3.5-2b",
        "base_url": "http://127.0.0.1:6008",
        "context_window": 262144,
        "max_tokens": 8192,
        "thinking": "low",
    },
}

ALIASES = {
    "1": "flash",
    "2": "sft",
    "3": "base",
    "flash": "flash",
    "sft": "sft",
    "base": "base",
}


def load():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def save(cfg):
    CONFIG.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def defaults(cfg):
    return cfg.setdefault("agents", {}).setdefault("defaults", {})


def ensure_local_provider(cfg, t):
    """注册 local-vllm provider（幂等），并把模型加入可路由列表。"""
    providers = cfg.setdefault("models", {}).setdefault("providers", {})
    prov = providers.setdefault(t["provider"], {})
    # vLLM 只挂载 /v1 前缀的 OpenAI 兼容路由（/v1/chat/completions），
    # OpenClaw 的 openai-completions api 会直接拼 /chat/completions，
    # 所以 baseUrl 必须带 /v1。
    prov["baseUrl"] = t["base_url"] + "/v1"
    prov["apiKey"] = ""
    prov["api"] = "openai-completions"
    ms = prov.setdefault("models", [])
    entry = next((m for m in ms if m.get("id") == t["model_id"]), None)
    if entry is None:
        entry = {
            "id": t["model_id"],
            "name": t["model_id"],
            "input": ["text"],
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        }
        ms.append(entry)
    # 组长实例启用了 --reasoning-parser qwen3：thinking 走 reasoning 字段
    entry.update(
        {
            "reasoning": True,
            "contextWindow": t["context_window"],
            "maxTokens": t["max_tokens"],
            "compat": {"thinkingFormat": "qwen"},
        }
    )
    defaults(cfg).setdefault("models", {})[t["primary"]] = {}


def set_thinking(cfg, level):
    d = defaults(cfg)
    if level == "medium":
        d.pop("thinkingDefault", None)  # 无键 = 网关默认 medium
    else:
        d["thinkingDefault"] = level


def clear_sessions():
    """清空主 agent 会话与微信上下文令牌（旧文件移到带时间戳的备份目录）。

    必须在网关停止后调用；返回被清理的文件路径列表。
    """
    stamp = time.strftime("%Y%m%d-%H%M%S")
    cleared = []
    sessions_dir = HOME / ".openclaw" / "agents" / "main" / "sessions"
    if sessions_dir.is_dir():
        backup = sessions_dir.parent / f"sessions.bak.{stamp}"
        shutil.move(str(sessions_dir), str(backup))
        sessions_dir.mkdir(parents=True, exist_ok=True)
        cleared.append(f"{backup}（会话记录已移走，重新建空目录）")
    acct_dir = HOME / ".openclaw" / "openclaw-weixin" / "accounts"
    if acct_dir.is_dir():
        for p in acct_dir.glob("*.context-tokens.json"):
            bak = p.with_name(p.name + f".bak.{stamp}")
            shutil.move(str(p), str(bak))
            cleared.append(f"{p} → {bak}")
    return cleared


def notify_reset():
    """切换后向微信发一条会话重置通知（确认机器人已开新对话）。"""
    acct_dir = HOME / ".openclaw" / "openclaw-weixin" / "accounts"
    target = None
    if acct_dir.is_dir():
        for p in acct_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                target = data.get("userId")
                if target:
                    break
            except Exception:
                continue
    if not target:
        print("[*] 未找到微信 userId，跳过重置通知")
        return
    env = dict(os.environ)
    env["PATH"] = str(OPENCLAW_BIN.parent) + os.pathsep + env.get("PATH", "")
    try:
        subprocess.run(
            [
                str(OPENCLAW_BIN),
                "message",
                "send",
                "--channel",
                "openclaw-weixin",
                "--target",
                target,
                "--message",
                "🔁 已切换模型并重置会话上下文，请发送任意消息开始新对话。",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        print(f"[*] 已向微信发送会话重置通知 ({target})")
    except Exception as exc:
        print(f"[!] 重置通知发送失败: {exc}")


def check_url(url, timeout=4):
    try:
        with urllib.request.urlopen(url + "/v1/models", timeout=timeout) as r:
            return r.status == 200, None
    except Exception as exc:
        return False, str(exc)


def current_primary(cfg):
    return cfg.get("agents", {}).get("defaults", {}).get("model", {}).get("primary")


def current_thinking(cfg):
    return cfg.get("agents", {}).get("defaults", {}).get("thinkingDefault", "medium")


def local_base_url(cfg):
    try:
        return (
            cfg["models"]["providers"]["local-vllm"].get("baseUrl", "")
        )
    except Exception:
        return ""


def restart_gateway(fresh=False, notify=False):
    env = dict(os.environ)
    env["PATH"] = str(OPENCLAW_BIN.parent) + os.pathsep + env.get("PATH", "")
    print("[*] 停止网关 ...")
    try:
        subprocess.run(
            [str(OPENCLAW_BIN), "gateway", "stop"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        print("[!] 停止超时，继续尝试启动")
    time.sleep(2)
    if fresh:
        for item in clear_sessions():
            print(f"[*] 已清空旧上下文: {item}")
        print("[*] 已强制开新会话（旧会话备份后可恢复）")
    print("[*] 启动网关 ...")
    log_f = open(str(HOME / "openclaw.log"), "ab")
    subprocess.Popen(
        [str(OPENCLAW_BIN), "gateway", "--port", str(GATEWAY_PORT)],
        stdin=subprocess.DEVNULL,
        stdout=log_f,
        stderr=log_f,
        env=env,
        start_new_session=True,
    )
    time.sleep(7)
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{GATEWAY_PORT}/health", timeout=5
        ) as r:
            healthy = r.status == 200
    except Exception:
        healthy = False
    line = None
    try:
        text = (HOME / "openclaw.log").read_text(encoding="utf-8", errors="replace")
        for ln in text.splitlines():
            if "agent model" in ln:
                line = ANSI_RE.sub("", ln).strip()
    except Exception:
        pass
    print("[*] 健康检查:", "OK" if healthy else "FAIL")
    if line:
        print("[*]", line)
    if fresh and notify:
        time.sleep(6)  # 等微信渠道重连后再发通知
        notify_reset()
    return healthy


def cmd_show(cfg):
    print("当前 primary:", current_primary(cfg))
    print("thinkingDefault:", current_thinking(cfg))
    url = local_base_url(cfg)
    if url:
        ok, err = check_url(url)
        print(f"vLLM 可达性 ({url}):", "OK" if ok else f"FAIL - {err}")
        if not ok:
            print("  提示: OpenClaw 在 WSL 里，访问不到 Windows 侧的 127.0.0.1 隧道。")
            print("  请在 WSL 里另建隧道: ssh -N -L 6006:127.0.0.1:6006 root@connect.nmb2.seetacloud.com -p 35547")


def cmd_switch(cfg, key, base_url, no_restart, force, thinking=None, fresh=True, notify=True):
    t = dict(TARGETS[key])
    if "provider" in t:
        url = (base_url or t["base_url"]).rstrip("/")
        ok, err = check_url(url)
        if not ok:
            print(f"[!] vLLM 不可达: {url} ({err})")
            print("    请在 WSL 里建隧道后重试，或加 --force 强制切换。")
            if not force:
                return 1
        t["base_url"] = url
    backup = CONFIG.with_name(CONFIG.name + ".bak-switch")
    shutil.copy(CONFIG, backup)
    if "provider" in t:
        ensure_local_provider(cfg, t)
    defaults(cfg).setdefault("model", {})["primary"] = t["primary"]
    set_thinking(cfg, thinking or t["thinking"])
    save(cfg)
    print(f"[*] primary -> {t['primary']}  (thinking={thinking or t['thinking']})")
    print(f"[*] 备份: {backup}")
    if no_restart:
        print("[*] 已跳过重启（--no-restart），手动重启网关后生效")
        return 0
    return 0 if restart_gateway(fresh=fresh, notify=notify) else 1


def main():
    ap = argparse.ArgumentParser(description="切换 OpenClaw 主模型")
    ap.add_argument("action", nargs="?", default=None)
    ap.add_argument("--base-url", help="vLLM 地址（默认 http://127.0.0.1:6006）")
    ap.add_argument("--no-restart", action="store_true", help="只改配置不重启网关")
    ap.add_argument("--force", action="store_true", help="vLLM 不可达时仍切换")
    ap.add_argument(
        "--thinking",
        choices=["off", "minimal", "low", "medium", "high", "xhigh", "max"],
        help="覆盖该模型的 thinking 档位（默认按目标预设，如 2b=off）",
    )
    ap.add_argument(
        "--keep-context",
        action="store_true",
        help="切换模型但保留旧会话上下文（默认强制清空）",
    )
    ap.add_argument(
        "--no-notify",
        action="store_true",
        help="切换后不发送微信重置通知（默认发送）",
    )
    args = ap.parse_args()

    action = args.action
    if action is not None:
        action = ALIASES.get(action, action)

    if action == "list":
        for k, t in TARGETS.items():
            print(f"{k:6s} {t['label']}")
        return 0

    cfg = load()
    if action == "show":
        cmd_show(cfg)
        return 0

    if action is None:
        print("选择要切换的模型：")
        for i, k in enumerate(TARGETS, 1):
            print(f"  {i}. {TARGETS[k]['label']}")
        try:
            inp = input("请输入 1/2/3: ").strip()
        except EOFError:
            return 0
        action = ALIASES.get(inp)
        if action is None:
            print("无效输入，请输入 1、2 或 3")
            return 1

    if action not in TARGETS:
        print(f"未知选项: {args.action}")
        return 1

    return cmd_switch(
        cfg,
        action,
        args.base_url,
        args.no_restart,
        args.force,
        args.thinking,
        fresh=not args.keep_context,
        notify=not args.no_notify,
    )


if __name__ == "__main__":
    sys.exit(main())
