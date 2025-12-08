# scash_manager/miner.py
import subprocess
import threading
import logging
import os
import signal
from typing import Optional


class Miner:
    """
    Miner 管理：

    - 负责启动 / 停止真实挖矿进程
    - cpuminer / SRBMiner / XMRig 三类都兼容
    - stdout 实时回调 push_log
    """

    def __init__(self, cfg, log_cb=None):
        self.cfg = cfg
        self.log_cb = log_cb or (lambda msg: None)
        self.proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._manual_stop_flag = False   # 前端点击停止 = True
        self._stdout_thread: Optional[threading.Thread] = None

    # ======================================================================
    # 工具方法
    # ======================================================================

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _log(self, msg: str):
        logging.info(msg)
        if self.log_cb:
            self.log_cb(msg)

    # ======================================================================
    # 构造启动命令
    # ======================================================================

    def _build_cmd(self):
        mcfg = self.cfg.get("miner", {}) or {}
        impl = mcfg.get("impl", "cpuminer")
        wallet = self.cfg.get("wallet")
        pool = mcfg.get("url")
        threads = mcfg.get("threads", 1)
        bin_path = mcfg.get("bin_path")
        algo = (mcfg.get("algorithm") or "randomx").strip()  # <--- 关键：使用配置里的算法

        if not bin_path:
            raise RuntimeError("未配置 miner 可执行文件路径 bin_path")

        # ---- cpuminer ----
        if impl == "cpuminer":
            # cpuminer 直接用 stratum+tcp://...
            # SCASH / XMR / ZEPH / WOW 这些 RandomX 系就用 randomx；
            # 如果将来你给它填别的 algo，这里也会跟着走。
            return [
                bin_path,
                "-a", algo,
                "-o", pool,
                "-u", wallet,
                "-p", "x",
                "-t", str(threads),
            ]

        # ---- XMRig ----
        elif impl == "xmrig":
            # XMRig：
            # - 普通 RandomX：algo = randomx
            # - WOW：algo = rx/wow
            # - DERO：algo = astrobwt
            # 这些都是前面 webapp 里根据币种算好的。
            return [
                bin_path,
                "-a", algo,
                "-o", pool,
                "-u", wallet,
                "-p", "x",
                "-t", str(threads),
            ]

        # ---- SRBMiner ----
        elif impl == "srbminer":
            # SRBMiner 使用 host:port（不带 stratum+tcp:// 前缀）
            hostport = pool.replace("stratum+tcp://", "").replace("stratum://", "")
            # 这里我们还是直接写死 randomscash，跟 webapp 里保持一致
            return [
                bin_path,
                "--algorithm", "randomscash",
                "--pool", hostport,
                "--wallet", wallet,
                "--password", "x",
                "--cpu-threads", str(threads),
            ]

        else:
            raise RuntimeError(f"未知 miner impl: {impl}")


    # ======================================================================
    # stdout 实时读取
    # ======================================================================

    def _reader(self, pipe):
        try:
            for line in iter(pipe.readline, b""):
                if not line:
                    break
                text = line.decode("utf-8", errors="ignore").rstrip()
                if text:
                    self._log(text)
        except Exception as e:
            self._log(f"[miner reader] 异常: {e}")
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    # ======================================================================
    # 启动 Miner
    # ======================================================================

    def start(self):
        with self._lock:
            if self.is_running():
                self._log("Miner 已在运行，无需再次启动。")
                return

            # 每次启动前都认为是“自动/正常启动”，允许 Watchdog 重启
            self._manual_stop_flag = False

            cmd = self._build_cmd()
            self._log(f"启动 Miner 进程: {' '.join(cmd)}")

            try:
                # 关键：把 Miner 放进单独的进程组，便于后面 killpg
                self.proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=1,
                    preexec_fn=os.setsid,   # 创建新进程组（Linux）
                )
            except Exception as e:
                self.proc = None
                self._log(f"启动 Miner 失败: {e}")
                return

            # stdout 线程
            if self.proc.stdout is not None:
                self._stdout_thread = threading.Thread(
                    target=self._reader,
                    args=(self.proc.stdout,),
                    daemon=True,
                )
                self._stdout_thread.start()

    # ======================================================================
    # 停止 Miner（前端点击停止）
    # ======================================================================

    def stop(self):
        """前端点击停止：杀掉整个进程树，而不是只杀一部分"""
        with self._lock:
            if not self.is_running():
                self._log("Miner 已停止。")
                return

            assert self.proc is not None
            pid = self.proc.pid
            self._manual_stop_flag = True  # 告诉 watchdog 不要重启
            self._log(f"正在停止 Miner (pid={pid})...")

            try:
                # 拿到进程组 ID
                pgid = os.getpgid(pid)
                self._log(f"向进程组 {pgid} 发送 SIGTERM（杀 Miner 所有子进程）")
                os.killpg(pgid, signal.SIGTERM)
            except Exception as e:
                self._log(f"SIGTERM 进程组失败：{e}，改用 terminate()")
                try:
                    self.proc.terminate()
                except Exception:
                    pass

            # 等待退出
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self._log("SIGTERM 无效，开始暴力 kill 进程树")

                try:
                    pgid = os.getpgid(pid)
                    os.killpg(pgid, signal.SIGKILL)
                except Exception as e:
                    self._log(f"SIGKILL 进程组失败：{e}")

                try:
                    self.proc.kill()
                except Exception:
                    pass

            # 关键：彻底再扫一遍，把 SRBMiner 残余进程全杀掉
            self._kill_residual_srbminer()

            rc = self.proc.returncode
            self.proc = None
            self._log(f"Miner 已停止，退出码={rc}")

    def _kill_residual_srbminer(self):
        """彻底清除系统里所有 SRBMiner 相关残余进程"""
        try:
            import psutil
        except ImportError:
            self._log("未安装 psutil，无法扫描残余 SRBMiner 进程。")
            return

        targets = ["SRBMiner-MULTI", "SRBMiner", "randomscash"]

        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = p.info["name"] or ""
                cmd = " ".join(p.info.get("cmdline") or [])

                if any(t in name for t in targets) or any(t in cmd for t in targets):
                    self._log(f"发现残余 SRBMiner 进程 pid={p.pid}，正在 kill -9")
                    try:
                        os.kill(p.pid, signal.SIGKILL)
                    except Exception:
                        pass
            except Exception:
                pass

    # ======================================================================
    # 被看门狗检测到时判断是否该重启
    # ======================================================================

    def should_restart(self) -> bool:
        """
        返回 True → Watchdog 会自动重启 Miner
        返回 False → 前端手动停止，不自动重启
        """
        if self._manual_stop_flag:
            return False
        return True
