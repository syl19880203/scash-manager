# scash_manager/watchdog.py
import time
import logging
import threading


class Watchdog:
    """
    负责监控 Miner：
    - Miner 异常退出 => 自动重启
    - 前端点击停止（manual_stop）=> 不自动重启
    """

    def __init__(self, miner, cfg):
        self.miner = miner
        self.cfg = cfg
        wcfg = cfg.get("watchdog", {}) or {}

        self.interval = int(wcfg.get("interval", 5))         # 每 5 秒检查一次
        self.restart_delay = int(wcfg.get("restart_delay", 10))
        self.restart_count = 0

        self._stop_flag = False
        self._running = False
        self._thread: threading.Thread | None = None

    # =========================================================
    # 外部接口
    # =========================================================

    def start(self):
        """启动 Watchdog（只允许启动一次）"""
        if self._running:
            return

        self._running = True
        self._stop_flag = False

        self._thread = threading.Thread(
            target=self.run,
            daemon=True,
        )
        self._thread.start()

        logging.info("[Watchdog] 已启动")

    def stop(self):
        """停止 Watchdog"""
        logging.info("[Watchdog] 收到 stop 信号")
        self._stop_flag = True
        self._running = False

    # =========================================================
    # Watchdog 主逻辑
    # =========================================================

    def run(self):
        """守护线程：定期检查 Miner 状态"""
        while not self._stop_flag:
            time.sleep(self.interval)

            if self._stop_flag:
                break

            running = self.miner.is_running()

            if running:
                # 正常运行
                continue

            # Miner 不在运行，检查是否允许自动重启
            if not self.miner.should_restart():
                logging.info(
                    "[Watchdog] 检测到 Miner 是前端手动停止，不执行自动重启。"
                )
                continue

            # 自动重启逻辑
            logging.warning("[Watchdog] 检测到 Miner 异常退出，准备自动重启...")
            time.sleep(self.restart_delay)

            try:
                self.miner.start()
                self.restart_count += 1
                logging.info(
                    f"[Watchdog] 自动重启成功，当前重启次数={self.restart_count}"
                )
            except Exception as e:
                logging.error(f"[Watchdog] 自动重启失败: {e}")

        logging.info("[Watchdog] run() 线程已退出")
