# scash_manager/miner_downloader.py
import logging
import os
import shutil
import tarfile
import tempfile
import platform
import urllib.request
import requests


"""
miner_downloader.py

提供两类矿工的自动下载与部署：

1. cpuminer-scash（官方）
   - 自动根据 CPU 架构选择 x86_64 / ARM64 / macOS
   - 自动下载并提取 minerd

2. SRBMiner-MULTI（第三方）
   - 自动下载 Linux 版本 v3.0.5
   - 自动查找 SRBMiner-MULTI 可执行文件

所有路径都在容器内。
"""


# ============================================================
#             CPUMINER DOWNLOAD CONFIGURATION
# ============================================================

CPUMINER_VERSION = "3.0.9"

CPUMINER_BASE = (
    f"https://github.com/scashnetwork/cpuminer-scash/releases/download/v{CPUMINER_VERSION}/{{fname}}"
)

CPUMINER_PACKAGES = {
    # Linux x86_64
    ("Linux", "x86_64"): "cpuminer-scash-3.0.9-linux-static-x64.tgz",
    ("Linux", "AMD64"):  "cpuminer-scash-3.0.9-linux-static-x64.tgz",

    # Linux ARM64
    ("Linux", "aarch64"): "cpuminer-scash-3.0.9-linux-static-arm64.tgz",
    ("Linux", "arm64"):   "cpuminer-scash-3.0.9-linux-static-arm64.tgz",

    # macOS M1/M2/M3
    ("Darwin", "arm64"):  "cpuminer-scash-3.0.9-macos-sonoma-arm64.tgz",
    ("Darwin", "aarch64"): "cpuminer-scash-3.0.9-macos-sonoma-arm64.tgz",
}


def _detect_platform() -> tuple[str, str]:
    """获取 (OS, ARCH)"""
    system = platform.system() or "Unknown"
    machine = platform.machine() or "Unknown"
    logging.info(f"[cpuminer] 平台识别: system={system}, machine={machine}")
    return system, machine


def _get_cpuminer_url() -> str:
    """根据平台选择合适的 cpuminer 包"""
    system, machine = _detect_platform()
    fname = CPUMINER_PACKAGES.get((system, machine))
    if not fname:
        raise RuntimeError(
            f"当前平台不支持自动下载 cpuminer，请手动放置可执行文件。\n"
            f"system={system}, arch={machine}"
        )
    return CPUMINER_BASE.format(fname=fname)


def _download_file(url: str, dest: str, timeout=120):
    """下载通用文件"""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    logging.info(f"[下载] {url}")

    try:
        with requests.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(8192):
                    if chunk:
                        f.write(chunk)
    except Exception as e:
        logging.error(f"下载失败: {e}")
        raise


def _extract_minerd(tgz_path: str, out_dir: str) -> str:
    """从 TGZ 中提取 minerd 文件"""
    with tarfile.open(tgz_path, "r:gz") as tar:
        members = [m for m in tar.getmembers() if m.isfile()]

        # 优先 minerd
        target = None
        for m in members:
            if os.path.basename(m.name) == "minerd":
                target = m
                break

        if not target:
            target = members[0]

        tar.extract(target, out_dir)
        full = os.path.join(out_dir, target.name)

        if not os.path.isfile(full):
            raise RuntimeError("解压成功但未找到 minerd")

        logging.info(f"[cpuminer] 解压成功 → {full}")
        return full


def ensure_cpuminer_binary(bin_path="/usr/local/bin/minerd"):
    """确保 cpuminer 存在，否则自动下载"""
    if os.path.isfile(bin_path):
        logging.info(f"[cpuminer] 已存在 → {bin_path}")
        return

    url = _get_cpuminer_url()

    with tempfile.TemporaryDirectory() as tmp:
        tgz_path = os.path.join(tmp, "cpuminer.tgz")

        _download_file(url, tgz_path)

        src = _extract_minerd(tgz_path, tmp)

        os.makedirs(os.path.dirname(bin_path), exist_ok=True)
        if os.path.exists(bin_path):
            os.remove(bin_path)

        shutil.move(src, bin_path)

    os.chmod(bin_path, 0o755)
    logging.info(f"[cpuminer] 已安装 → {bin_path}")


# ============================================================
#                 SRBMiner AUTOINSTALL MODULE
# ============================================================

SRB_URL = (
    "https://github.com/doktor83/SRBMiner-Multi/releases/download/"
    "3.0.5/SRBMiner-Multi-3-0-5-Linux.tar.gz"
)

def ensure_srbminer(base_dir="/opt/SRBMiner-Multi") -> str:
    """
    自动下载 SRBMiner-MULTI v3.0.5（Linux）
    返回：可执行文件路径 /opt/SRBMiner-Multi/SRBMiner-MULTI
    """
    exe_path = os.path.join(base_dir, "SRBMiner-MULTI")

    # 已存在 → 直接返回
    if os.path.isfile(exe_path):
        logging.info(f"[SRBMiner] 已存在 → {exe_path}")
        return exe_path

    # 下载
    tmp_tar = "/tmp/SRBMiner.tar.gz"
    logging.info(f"[SRBMiner] 开始下载: {SRB_URL}")

    try:
        urllib.request.urlretrieve(SRB_URL, tmp_tar)
    except Exception as e:
        raise RuntimeError(f"无法下载 SRBMiner：{e}")

    # 解压
    extract_dir = "/tmp/srbminer_extract"
    if os.path.isdir(extract_dir):
        shutil.rmtree(extract_dir)
    os.makedirs(extract_dir)

    try:
        with tarfile.open(tmp_tar, "r:gz") as tar:
            tar.extractall(extract_dir)
    except Exception as e:
        raise RuntimeError(f"SRBMiner 解压失败：{e}")

    # 查找可执行文件
    real_exe = None
    for root, dirs, files in os.walk(extract_dir):
        if "SRBMiner-MULTI" in files:
            real_exe = os.path.join(root, "SRBMiner-MULTI")
            break

    if not real_exe:
        raise RuntimeError("解压完成但未找到 SRBMiner-MULTI")

    os.makedirs(base_dir, exist_ok=True)

    # 移动到正式路径
    shutil.move(real_exe, exe_path)
    os.chmod(exe_path, 0o755)

    logging.info(f"[SRBMiner] 安装成功 → {exe_path}")
    return exe_path
