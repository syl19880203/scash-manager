# scash_manager/webapp.py
import logging
import threading
import time
import os
import re
from collections import deque

from flask import Flask, jsonify, request, render_template

from .config import load_config, save_config, setup_logging
from .miner import Miner
from .watchdog import Watchdog
from .miner_downloader import ensure_cpuminer_binary, ensure_srbminer, ensure_xmrig_binary  # <-- 保留

# ===== 币种预设：默认算法 + 示例矿池（可用） =====

COIN_PRESETS = {
    "scash": {
        "label": "SCASH",
        # 推荐：cpuminer-scash + pool.scash.pro
        "default_pool": "pool.scash.pro:8888",
        # cpuminer / xmrig 都跑 RandomX，SCASH 实际是 RandomX 的变种，
        # cpuminer 用 randomx 即可。
        "algo_cpuminer": "randomx",
        "algo_xmrig": "randomx",  # 仅当你自己找兼容 SCASH 的 XMRig 池子
    },
    "xmr": {
        "label": "Monero (XMR)",
        # SupportXMR 官方矿池示例
        "default_pool": "pool.supportxmr.com:3333",  # stratum+tcp:// 前缀由我们自动补
        "algo_cpuminer": "randomx",
        "algo_xmrig": "randomx",  # XMRig 内部会协商 rx/0
    },
    "dero": {
        "label": "DERO",
        # HeroMiners DERO AstroBWT 矿池示例（AstroBWT）
        "default_pool": "us.dero.herominers.com:10120",
        "algo_cpuminer": None,       # cpuminer 不跑 dero
        "algo_xmrig": "astrobwt",    # 关键：Dero 用 AstroBWT
    },
    "wow": {
        "label": "Wownero (WOW)",
        # HeroMiners WOW RandomX 矿池示例
        "default_pool": "wownero.herominers.com:10661",
        "algo_cpuminer": "randomx",  # 一般建议 XMRig，这里仍然标 randomx
        "algo_xmrig": "rx/wow",      # XMRig 支持 rx/wow
    },
    "zeph": {
        "label": "Zephyr (ZEPH)",
        # Kryptex Zeph RandomX 矿池示例
        "default_pool": "zeph.kryptex.network:7030",
        "algo_cpuminer": "randomx",
        "algo_xmrig": "randomx",     # Zeph 也是 RandomX 变种，XMRig 用 randomx 即可
    },
}



def _strip_stratum_prefix(pool_url: str) -> str:
    """
    把 stratum+tcp://pool.scash.pro:8888 转成 pool.scash.pro:8888
    供 SRBMiner 使用。
    """
    if not pool_url:
        return ""
    for prefix in ("stratum+tcp://", "stratum+ssl://", "stratum://"):
        if pool_url.startswith(prefix):
            return pool_url[len(prefix):]
    return pool_url


def _normalize_pool_for_cpuminer(pool_url: str) -> str:
    """
    cpuminer / XMRig 需要 stratum+tcp:// 前缀。
    - 如果用户已经写了 stratum+tcp:// / stratum+ssl:// / stratum://：原样使用
    - 如果只写 host:port：自动补成 stratum+tcp://host:port
    """
    if not pool_url:
        return ""
    if pool_url.startswith(("stratum+tcp://", "stratum+ssl://", "stratum://")):
        return pool_url
    # 用户只写了 IP:端口 / 域名:端口
    return f"stratum+tcp://{pool_url}"


def _config_ready(cfg: dict) -> bool:
    """只看钱包 + 矿池是否填了，用来决定是否进入向导。"""
    wallet = (cfg.get("wallet") or "").strip()
    mcfg = cfg.get("miner", {}) or {}
    url = (mcfg.get("url") or "").strip()
    return bool(wallet and url)


# ===== 简单日志缓冲，供前端 /api/logs 使用 =====
log_buffer = deque(maxlen=500)
log_lock = threading.Lock()

# 检测「已经带时间戳」的行，例如：[2025-12-01 11:36:55] ...
TS_PREFIX_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
# 解析 accepted 行中的时间戳
TIME_RE = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")

# 匹配 accepted 行
SUBMIT_LINE_RE = re.compile(r"accepted:\s*\d+/\d+", re.IGNORECASE)


def push_log(raw_msg: str):
    """
    写 Python 日志 + 写入内存缓冲：
    - 支持 msg 里自带的 \n / \r\n；
    - 每一行都会加上统一时间戳；
    - 如果 Miner 输出本身已经是 [YYYY-MM-DD HH:MM:SS] 前缀，就不再重复加第二个时间戳。
    - 同时去掉 ANSI 颜色控制码，避免影响正则匹配算力 / accepted。
    """
    if raw_msg is None:
        return

    msg = str(raw_msg).replace("\r\n", "\n").replace("\r", "\n")
    msg = msg.replace("\\n", "\n")

    with log_lock:
        for line in msg.split("\n"):
            line = line.strip()
            # 去掉 ANSI 颜色码
            line = ANSI_RE.sub("", line)
            if not line:
                continue

            if TS_PREFIX_RE.match(line):
                entry = line
            else:
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                entry = f"[{ts}] {line}"

            logging.info(entry)
            log_buffer.append(entry)


# ===== 从日志里解析算力，用于前端展示 =====

# 支持 "0.11 khash/s"、"12.3 H/s"、"1.5 MH/s" 等
HASHRATE_RE = re.compile(
    r"(?P<val>\d+(\.\d+)?)\s*(?P<unit>([kKmMgGtT]?hash/s|[kKmMgGtT]?H/s))"
)

UNIT_MAP = {
    "H/s": 1,
    "hash/s": 1,
    "kh/s": 1_000,
    "khash/s": 1_000,
    "mh/s": 1_000_000,
    "mhash/s": 1_000_000,
    "gh/s": 1_000_000_000,
    "ghash/s": 1_000_000_000,
    "th/s": 1_000_000_000_000,
    "thash/s": 1_000_000_000_000,
}


def _parse_hashrate_from_logs():
    """
    从当前内存日志中解析最近一次算力信息。
    返回:
        {"raw": "0.11 khash/s", "hs": 110.0}
        如果没找到则返回 None。
    """
    with log_lock:
        text = "\n".join(log_buffer)

    matches = list(HASHRATE_RE.finditer(text))
    if not matches:
        return None

    last = matches[-1]
    val = float(last.group("val"))
    unit = last.group("unit")
    key = unit.lower()
    mul = UNIT_MAP.get(key, UNIT_MAP.get(unit, 1))
    return {
        "raw": f"{val} {unit}",
        "hs": val * mul,
    }


def _parse_last_submit_from_logs():
    """
    查找最近一条 accepted: 行，并提取其中的时间戳，作为“最后提交”。
    优先使用行里最后一个 [YYYY-MM-DD HH:MM:SS]。
    """
    with log_lock:
        lines = list(log_buffer)

    last_line = None
    for line in lines:
        if SUBMIT_LINE_RE.search(line):
            last_line = line

    if not last_line:
        return None

    times = TIME_RE.findall(last_line)
    ts_str = times[-1] if times else None
    return {"line": last_line, "time_str": ts_str}


def _humanize_hs(v: float | None) -> str | None:
    """把 H/s 数值格式化为 '123.45 H/s'，如果为 None 则返回 None。"""
    if v is None:
        return None
    return f"{v:.2f} H/s"


# ===== 算力历史，用于折线图（3 分钟一个点，保留最近 24h 左右） =====
HASH_HISTORY = []  # list[(ts:int, hs:float)]
HASH_HISTORY_LOCK = threading.Lock()
HISTORY_MIN_INTERVAL = 180  # 每 3 分钟最多记录一个点
HISTORY_MAX_POINTS = 600  # 大约 24h 级别


def _update_hashrate_history(current_hs: float):
    """把当前算力写入历史（>=3 分钟才追加一个点）。"""
    now = int(time.time())
    with HASH_HISTORY_LOCK:
        if HASH_HISTORY:
            last_ts, _ = HASH_HISTORY[-1]
            if now - last_ts < HISTORY_MIN_INTERVAL:
                HASH_HISTORY[-1] = (last_ts, current_hs)
            else:
                HASH_HISTORY.append((now, current_hs))
        else:
            HASH_HISTORY.append((now, current_hs))

        if len(HASH_HISTORY) > HISTORY_MAX_POINTS:
            HASH_HISTORY[:] = HASH_HISTORY[-HISTORY_MAX_POINTS:]


def _compute_history_stats():
    """
    基于 HASH_HISTORY 计算：
    - 简单平均算力 (avg_hs)
    - EWMA 平滑算力 (ewma_hs)
    - 每个点对应的 EWMA，用于曲线。
    """
    with HASH_HISTORY_LOCK:
        pts = list(HASH_HISTORY)

    if not pts:
        return None

    vals = [hs for _, hs in pts]

    alpha = 0.3
    ewma_list: list[float] = []
    cur = None
    for v in vals:
        if cur is None:
            cur = v
        else:
            cur = alpha * v + (1 - alpha) * cur
        ewma_list.append(cur)

    avg = sum(vals) / len(vals)
    points = []
    for (ts, hs), ew in zip(pts, ewma_list):
        points.append({"ts": ts, "hs": hs, "ewma_hs": ew})

    return {"avg_hs": avg, "ewma_hs": ewma_list[-1], "points": points}


# ===== Flask App 初始化（模板 + 静态文件目录） =====

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(
    __name__,
    template_folder=TEMPLATE_DIR,
    static_folder=STATIC_DIR,
)

# 初始化全局状态
_cfg = load_config(allow_missing=True)
if _cfg is None:
    _cfg = {}
setup_logging(_cfg or {})
logging.info("SCASH Manager WebApp 启动中...")
push_log("SCASH Manager Web 控制台已启动。")

miner_cfg = _cfg.get("miner", {}) or {}
_cfg["miner"] = miner_cfg  # 确保存在

# 默认币种，如果配置里没写就视为 scash
if "coin" not in _cfg:
    _cfg["coin"] = "scash"

_miner: Miner | None = None
_watchdog: Watchdog | None = None


def ensure_objects(force: bool = False):
    """
    在配置完整的前提下，懒加载 Miner / Watchdog。
    force=True 时会先重建对象（例如 /api/setup 之后）。
    """
    global _cfg, _miner, _watchdog

    if not _config_ready(_cfg):
        return

    if force:
        _miner = None
        _watchdog = None

    if _miner is None:
        _miner = Miner(_cfg, log_cb=push_log)

    if _watchdog is None:
        _watchdog = Watchdog(_miner, _cfg)
        t = threading.Thread(target=_watchdog.run, daemon=True)
        t.start()


# ===== 路由部分 =====

@app.route("/")
def index():
    # 渲染 templates/index.html
    return render_template("index.html")


@app.get("/api/status")
def api_status():
    global _cfg, _miner, _watchdog

    ensure_objects()

    needs_setup = not _config_ready(_cfg)
    mcfg = _cfg.get("miner", {}) or {}
    wcfg = _cfg.get("watchdog", {}) or {}

    running = _miner.is_running() if _miner else False
    hr = _parse_hashrate_from_logs()

    avg_hs = None
    ewma_hs = None
    if hr:
        _update_hashrate_history(hr["hs"])
        stats = _compute_history_stats()
        if stats:
            avg_hs = stats["avg_hs"]
            ewma_hs = stats["ewma_hs"]

    submit_info = _parse_last_submit_from_logs()

    return jsonify(
        {
            "ok": True,
            "needs_setup": needs_setup,
            "running": running,
            "coin": _cfg.get("coin", "scash"),  # <-- 返回币种给前端
            "wallet": _cfg.get("wallet"),
            "pool_url": mcfg.get("url"),
            "threads": mcfg.get("threads"),
            "bin_path": mcfg.get("bin_path"),
            "algorithm": mcfg.get("algorithm"),
            "impl": mcfg.get("impl", "cpuminer"),
            "restart_count": _watchdog.restart_count if _watchdog else 0,
            "restart_delay": wcfg.get("restart_delay", 5),
            # 算力：
            "hashrate": hr["raw"] if hr else None,
            "hashrate_hs": hr["hs"] if hr else None,
            "hashrate_avg_hs": avg_hs,
            "hashrate_ewma_hs": ewma_hs,
            "hashrate_avg": _humanize_hs(avg_hs),
            "hashrate_ewma": _humanize_hs(ewma_hs),
            # 最近 accepted 时间
            "last_submit": submit_info["time_str"] if submit_info else None,
        }
    )


@app.get("/api/hashrate-history")
def api_hashrate_history():
    """
    返回折线图所需的算力历史。
    points: [{ts, hs, ewma_hs}, ...]
    """
    hr = _parse_hashrate_from_logs()
    if hr:
        _update_hashrate_history(hr["hs"])
    stats = _compute_history_stats()
    if not stats:
        return jsonify({"ok": True, "points": []})
    return jsonify({"ok": True, "points": stats["points"]})


@app.get("/api/logs")
def api_logs():
    with log_lock:
        text = "\n".join(log_buffer)
    return jsonify({"logs": text, "ok": True})


@app.post("/api/setup")
def api_setup():
    """
    body: {coin, impl, wallet, pool_url, bin_path, threads?}

    统一流程：
    1. 更新并保存配置
    2. 下载 / 校验 miner 二进制（cpuminer / SRBMiner / XMRig）
    3. 成功后重建 Miner / Watchdog 并启动 Miner
    """
    global _cfg, _miner, _watchdog

    try:
        data = request.get_json(force=True) or {}
        coin = (data.get("coin") or "scash").strip().lower()  # 新增：币种
        impl = (data.get("impl") or "cpuminer").strip()
        wallet = (data.get("wallet") or "").strip()
        pool_url_raw = (data.get("pool_url") or "").strip()
        bin_path = (data.get("bin_path") or "").strip()
        threads = data.get("threads")

        if not wallet:
            return jsonify({"ok": False, "error": "钱包地址不能为空"}), 400
        if not pool_url_raw:
            return jsonify({"ok": False, "error": "矿池地址不能为空"}), 400

        # 基本线程检查
        if threads is None:
            auto_threads = max(1, (os.cpu_count() or 2) - 1)
            threads = auto_threads

        try:
            threads = int(threads)
            if threads <= 0:
                raise ValueError
        except Exception:
            return jsonify({"ok": False, "error": "线程数必须是正整数"}), 400

        # 一些安全限制 / 防呆：
        # 1) 非 scash 币种不要使用 SRBMiner（当前 extra_args 写死了 randomscash）
        if coin != "scash" and impl == "srbminer":
            return jsonify(
                {
                    "ok": False,
                    "error": "当前版本仅支持 SCASH 使用 SRBMiner，其它币种请使用 cpuminer 或 XMRig。",
                }
            ), 400

        # 2) SCASH + XMRig + pool.scash.pro 组合直接拒绝（矿池协议不兼容）
        if (
            coin == "scash"
            and impl == "xmrig"
            and "pool.scash.pro" in pool_url_raw
        ):
            return jsonify(
                {
                    "ok": False,
                    "error": "SCASH 官方矿池 pool.scash.pro 暂不支持 XMRig 协议，请改用 cpuminer 或 SRBMiner。",
                }
            ), 400

        # 根据 impl 规范化矿池地址
        if impl in ("cpuminer", "xmrig"):
            pool_url = _normalize_pool_for_cpuminer(pool_url_raw)
        else:
            # SRBMiner 用 host:port，extra_args 里单独处理
            pool_url = pool_url_raw

        # 1) 更新配置（全局 coin）
        _cfg["coin"] = coin
        _cfg["wallet"] = wallet
        mcfg = _cfg.get("miner", {}) or {}
        mcfg["impl"] = impl
        mcfg["url"] = pool_url
        mcfg["user"] = wallet
        mcfg["threads"] = threads

        # bin_path 默认值
        if bin_path:
            mcfg["bin_path"] = bin_path
        else:
            if impl == "cpuminer":
                mcfg["bin_path"] = "/usr/local/bin/minerd"
            elif impl == "xmrig":
                mcfg["bin_path"] = "/usr/local/bin/xmrig"
            else:
                mcfg["bin_path"] = "/opt/SRBMiner-Multi/SRBMiner-MULTI"

        # 根据 impl + coin 填充算法（algorithm / extra_args），只是给前端展示和 Miner 用
        preset = COIN_PRESETS.get(coin, COIN_PRESETS["scash"])

        if impl == "cpuminer":
            # cpuminer 这边目前只考虑 RandomX 系币，
            # DERO 这种 AstroBWT 的我们直接提示用 XMRig。
            algo = preset.get("algo_cpuminer") or "randomx"
            if coin == "dero" and preset.get("algo_cpuminer") is None:
                # 只是日志提示，不 hard block，方便你自己玩
                logging.info("警告：你选择了 DERO + cpuminer，建议改用 XMRig (astrobwt)")
                push_log("提示：DERO 建议使用 XMRig + astrobwt 算法，cpuminer 目前不推荐。")

            mcfg["algorithm"] = algo
            mcfg["extra_args"] = ""

        elif impl == "xmrig":
            # XMRig：根据币种切算法
            # - SCASH / XMR / ZEPH → randomx（池子下发具体 variant）
            # - WOW → rx/wow
            # - DERO → astrobwt
            algo = preset.get("algo_xmrig") or "randomx"

            mcfg["algorithm"] = algo
            mcfg["extra_args"] = ""

        elif impl == "srbminer":
            # SRBMiner：只用于 SCASH（randomscash）
            host_port = _strip_stratum_prefix(pool_url_raw)
            mcfg["algorithm"] = "randomscash"
            mcfg["extra_args"] = (
                f"--algorithm randomscash "
                f"--pool {host_port} "
                f"--wallet {wallet} "
                f"--password x "
                f"--cpu-threads {threads} "
                f"--enable-large-pages"
            )

        _cfg["miner"] = mcfg


        if "logging" not in _cfg:
            _cfg["logging"] = {
                "file": "/data/scash-manager.log",
                "level": "INFO",
            }

        save_config(_cfg)
        logging.info("已更新配置并写入文件。")
        push_log(
            f"已保存配置：coin={coin}, impl={impl}, 线程={threads}。正在准备矿工程序..."
        )

        # 2) 下载 / 校验 miner
        try:
            if impl == "cpuminer":
                ensure_cpuminer_binary(mcfg["bin_path"])

            elif impl == "srbminer":
                exe_path = ensure_srbminer(
                    os.path.dirname(mcfg["bin_path"]) or "/opt/SRBMiner-Multi"
                )
                mcfg["bin_path"] = exe_path
                _cfg["miner"] = mcfg
                save_config(_cfg)

            elif impl == "xmrig":
                ensure_xmrig_binary(mcfg["bin_path"])

            else:
                raise RuntimeError(f"未知的 miner impl: {impl}")

            # 最终二次兜底校验
            if not os.path.isfile(mcfg["bin_path"]):
                raise FileNotFoundError(mcfg["bin_path"])

        except Exception as e:
            logging.error("配置后准备 miner 失败: %s", e)
            push_log(f"矿工程序不存在或下载失败: {e}")

            if _watchdog:
                _watchdog.stop()
            if _miner and _miner.is_running():
                _miner.stop()

            _watchdog = None
            _miner = None

            return jsonify(
                {
                    "ok": False,
                    "error": (
                        "矿工程序不存在或下载失败："
                        "常见原因是无法连接 GitHub 或下载中途被重置，"
                        "请检查网络，或者手动把 cpuminer / SRBMiner / XMRig "
                        "放到容器内指定路径后重试。"
                        f"（详细错误：{e}）"
                    ),
                }
            )

        # 3) 一切正常，重建 Miner / Watchdog 并启动
        if _watchdog:
            _watchdog.stop()
            _watchdog = None
        if _miner and _miner.is_running():
            _miner.stop()
        _miner = None

        ensure_objects(force=True)

        if _miner:
            _miner.start()

        return jsonify({"ok": True})

    except Exception as e:
        logging.exception("api_setup 处理失败")
        push_log(f"api_setup 处理失败: {e}")
        return jsonify({"ok": False, "error": f"内部错误: {e}"}), 500


@app.post("/api/start")
def api_start():
    global _cfg, _miner
    if not _config_ready(_cfg):
        return jsonify({"ok": False, "error": "配置未完成，请先在向导中填写钱包和矿池。"}), 400

    ensure_objects()

    if not _miner:
        return jsonify({"ok": False, "error": "内部错误：Miner 未初始化"}), 500

    _miner.start()
    return jsonify({"ok": True, "message": "已请求启动 Miner"})


@app.post("/api/stop")
def api_stop():
    """
    前端点击“停止”：
    - Watchdog 也要停掉，防止自动拉起
    """
    global _miner, _watchdog

    logging.info("收到 /api/stop 请求，准备停止 Miner 和 Watchdog。")
    push_log("前端请求停止 Miner，正在停止 Miner + Watchdog。")

    if _watchdog is not None:
        try:
            _watchdog.stop()
        except Exception as e:
            logging.error("停止 Watchdog 时出错: %s", e)

    if _miner is not None:
        try:
            _miner.stop()
        except Exception as e:
            logging.error("停止 Miner 时出错: %s", e)

    return jsonify({"ok": True})


@app.post("/api/reset-config")
def api_reset_config():
    """
    清空钱包和矿池配置，停掉 Miner 和 Watchdog，
    让前端重新回到首次配置向导。
    """
    global _cfg, _miner, _watchdog

    if _watchdog:
        _watchdog.stop()
        _watchdog = None

    if _miner and _miner.is_running():
        _miner.stop()
    _miner = None

    _cfg["wallet"] = ""
    _cfg["coin"] = "scash"
    mcfg = _cfg.get("miner", {}) or {}
    mcfg["url"] = ""
    mcfg["user"] = ""
    _cfg["miner"] = mcfg

    save_config(_cfg)
    logging.info("已通过 /api/reset-config 清空钱包和矿池配置。")
    push_log("已清空钱包和矿池配置，现在可以重新运行向导。")

    return jsonify({"ok": True, "message": "配置已清空，现在可以重新运行向导。"})


def main():
    logging.info("SCASH Manager Web 控制台已启动：http://0.0.0.0:8080")
    app.run(host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
