// static/js/app.js
document.addEventListener("DOMContentLoaded", () => {
  const setupSection = document.getElementById("setup-section");
  const dashSection = document.getElementById("dashboard-section");

  const coinSelect = document.getElementById("setup-coin");
  const implSelect = document.getElementById("setup-impl");
  const poolSelect = document.getElementById("setup-pool");
  const poolCustomInput = document.getElementById("setup-pool-custom");
  const walletInput = document.getElementById("setup-wallet");
  const threadsInput = document.getElementById("setup-threads");
  const binInput = document.getElementById("setup-bin");
  const setupMsg = document.getElementById("setup-msg");

  const btnSetupSave = document.getElementById("btn-setup-save");
  const btnReset = document.getElementById("btn-reset");
  const btnStart = document.getElementById("btn-start");
  const btnStop = document.getElementById("btn-stop");
  const btnRefresh = document.getElementById("btn-refresh");
  const dashMsg = document.getElementById("dash-msg");

  const statusBadge = document.getElementById("status-badge");
  const statusText = document.getElementById("status-text");
  const coinText = document.getElementById("coin-text");
  const implText = document.getElementById("impl-text");
  const walletText = document.getElementById("wallet");
  const poolUrlText = document.getElementById("pool-url");
  const threadsText = document.getElementById("threads");
  const binPathText = document.getElementById("bin-path");
  const algoText = document.getElementById("algo");
  const restartCountText = document.getElementById("restart-count");
  const restartDelayText = document.getElementById("restart-delay");

  const hashrateText = document.getElementById("hashrate");
  const hashrateAvgText = document.getElementById("hashrate-avg");
  const hashrateEwmaText = document.getElementById("hashrate-ewma");
  const hashrateHsText = document.getElementById("hashrate-hs");
  const lastSubmitText = document.getElementById("last-submit");

  const logBox = document.getElementById("log-box");

  // ================== 币种 ↔ 矿池 ↔ 矿工类型 联动 ==================

  function updatePoolByCoin() {
    const coin = coinSelect.value;

    // 自定义 RandomX：强制自定义矿池
    if (coin === "custom_rx") {
      poolSelect.value = "custom";
      poolCustomInput.classList.remove("hidden");
      return;
    }

    let matched = null;
    for (const opt of poolSelect.options) {
      if (opt.dataset.coin === coin) {
        matched = opt;
        break;
      }
    }

    if (matched) {
      poolSelect.value = matched.value;
      poolCustomInput.classList.add("hidden");
    } else {
      poolSelect.value = "custom";
      poolCustomInput.classList.remove("hidden");
    }
  }

  function updateImplByCoin() {
    const coin = coinSelect.value;
    let firstEnabledValue = null;

    for (const opt of implSelect.options) {
      const coinsStr = opt.dataset.coins || "";
      if (!coinsStr) {
        opt.disabled = false;
      } else {
        const list = coinsStr.split(",").map(s => s.trim());
        opt.disabled = !list.includes(coin);
      }
      if (!opt.disabled && !firstEnabledValue) {
        firstEnabledValue = opt.value;
      }
    }

    if (implSelect.selectedOptions[0]?.disabled && firstEnabledValue) {
      implSelect.value = firstEnabledValue;
    }
  }

  poolSelect.addEventListener("change", () => {
    if (poolSelect.value === "custom") {
      poolCustomInput.classList.remove("hidden");
    } else {
      poolCustomInput.classList.add("hidden");
    }
  });

  coinSelect.addEventListener("change", () => {
    updatePoolByCoin();
    updateImplByCoin();
  });

  // 初始执行一次
  updatePoolByCoin();
  updateImplByCoin();

  // ================== ApexCharts：算力曲线 ==================

  let hashrateChart = null;

  function initChart() {
    if (hashrateChart) return;

    const options = {
      chart: {
        type: "line",
        height: 260,
        toolbar: { show: false },
        zoom: { enabled: false }
      },
      series: [
        { name: "算力 H/s", data: [] },
        { name: "平滑算力 H/s", data: [] }
      ],
      xaxis: {
        type: "datetime",
        labels: { datetimeUTC: false }
      },
      yaxis: {
        labels: {
          formatter: val => {
            if (val >= 1e9) return (val / 1e9).toFixed(2) + " GH/s";
            if (val >= 1e6) return (val / 1e6).toFixed(2) + " MH/s";
            if (val >= 1e3) return (val / 1e3).toFixed(2) + " kH/s";
            return val.toFixed(2) + " H/s";
          }
        }
      },
      stroke: {
        curve: "smooth",
        width: 2
      },
      dataLabels: { enabled: false },
      legend: { position: "top" },
      tooltip: {
        x: { format: "yyyy-MM-dd HH:mm:ss" }
      }
    };

    hashrateChart = new ApexCharts(
      document.querySelector("#hashrate-chart"),
      options
    );
    hashrateChart.render();
  }

  async function loadHashrateHistory() {
    try {
      const resp = await fetch("/api/hashrate-history");
      const data = await resp.json();
      if (!data.ok) return;
      const pts = data.points || [];

      const series1 = pts.map(p => [p.ts * 1000, p.hs]);
      const series2 = pts.map(p => [p.ts * 1000, p.ewma_hs]);

      if (!hashrateChart) initChart();
      hashrateChart.updateSeries([
        { name: "算力 H/s", data: series1 },
        { name: "平滑算力 H/s", data: series2 }
      ]);
    } catch (e) {
      console.error("loadHashrateHistory error:", e);
    }
  }

  // ================== 状态 / 日志 ==================

  function setStatusBadge(running) {
    if (running) {
      statusBadge.classList.remove("off");
      statusBadge.classList.add("on");
      statusText.textContent = "运行中";
    } else {
      statusBadge.classList.remove("on");
      statusBadge.classList.add("off");
      statusText.textContent = "已停止";
    }
  }

  async function loadStatus() {
    try {
      const resp = await fetch("/api/status");
      const data = await resp.json();

      if (!data.ok) {
        dashMsg.textContent = data.error || "获取状态失败";
        return;
      }

      if (data.needs_setup) {
        // 需要首次配置：显示向导
        setupSection.classList.remove("hidden");
        dashSection.classList.add("hidden");
      } else {
        // 已有配置：显示控制台
        setupSection.classList.add("hidden");
        dashSection.classList.remove("hidden");
      }

      setStatusBadge(data.running);

      coinText.textContent = data.coin || "-";
      implText.textContent = data.impl || "-";
      walletText.textContent = data.wallet || "-";
      poolUrlText.textContent = data.pool_url || "-";
      threadsText.textContent = data.threads ?? "-";
      binPathText.textContent = data.bin_path || "-";
      algoText.textContent = data.algorithm || "-";
      restartCountText.textContent = data.restart_count ?? 0;
      restartDelayText.textContent = data.restart_delay ?? "-";

      hashrateText.textContent = data.hashrate || "未知";
      hashrateAvgText.textContent = data.hashrate_avg || "-";
      hashrateEwmaText.textContent = data.hashrate_ewma || "-";
      hashrateHsText.textContent =
        typeof data.hashrate_hs === "number"
          ? data.hashrate_hs.toFixed(2)
          : "-";
      lastSubmitText.textContent = data.last_submit || "-";
    } catch (e) {
      console.error("loadStatus error:", e);
      dashMsg.textContent = "获取状态失败：" + e;
    }
  }

  async function loadLogs() {
    try {
      const resp = await fetch("/api/logs");
      const data = await resp.json();
      if (!data.ok) return;
      logBox.textContent = data.logs || "";
      logBox.scrollTop = logBox.scrollHeight;
    } catch (e) {
      console.error("loadLogs error:", e);
    }
  }

  async function refreshAll() {
    await loadStatus();
    await loadLogs();
    await loadHashrateHistory();
  }

  // ================== 按钮事件 ==================

  btnSetupSave.addEventListener("click", async () => {
    setupMsg.textContent = "";
    dashMsg.textContent = "";

    const coin = coinSelect.value;
    const impl = implSelect.value;
    const wallet = walletInput.value.trim();

    const poolUrl =
      poolSelect.value === "custom"
        ? poolCustomInput.value.trim()
        : poolSelect.value.trim();

    const binPath = binInput.value.trim();
    const threadsVal = threadsInput.value.trim();
    const threads = threadsVal === "" ? null : Number(threadsVal);

    if (!wallet) {
      setupMsg.textContent = "钱包地址不能为空";
      return;
    }
    if (!poolUrl) {
      setupMsg.textContent = "矿池地址不能为空";
      return;
    }
    if (threads !== null && (!Number.isInteger(threads) || threads <= 0)) {
      setupMsg.textContent = "线程数必须是正整数";
      return;
    }

    setupMsg.textContent = "正在保存配置并准备 Miner...";

    try {
      const resp = await fetch("/api/setup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          coin,
          impl,
          wallet,
          pool_url: poolUrl,
          bin_path: binPath,
          threads
        })
      });

      const data = await resp.json();
      if (!data.ok) {
        setupMsg.textContent = data.error || "保存配置失败";
        return;
      }

      setupMsg.textContent = "配置已保存，Miner 正在启动...";
      await refreshAll();
    } catch (e) {
      console.error("setup error:", e);
      setupMsg.textContent = "保存配置失败：" + e;
    }
  });

  btnReset.addEventListener("click", async () => {
    dashMsg.textContent = "";
    setupMsg.textContent = "";
    try {
      const resp = await fetch("/api/reset-config", { method: "POST" });
      const data = await resp.json();
      if (!data.ok) {
        dashMsg.textContent = data.error || "重置配置失败";
        return;
      }
      dashMsg.textContent = data.message || "配置已清空";
      // 重置界面为首次配置状态
      setupSection.classList.remove("hidden");
      dashSection.classList.add("hidden");
    } catch (e) {
      dashMsg.textContent = "重置配置失败：" + e;
    }
  });

  btnStart.addEventListener("click", async () => {
    dashMsg.textContent = "正在请求启动 Miner...";
    try {
      const resp = await fetch("/api/start", { method: "POST" });
      const data = await resp.json();
      if (!data.ok) {
        dashMsg.textContent = data.error || "启动失败";
        return;
      }
      dashMsg.textContent = data.message || "已请求启动 Miner";
      await refreshAll();
    } catch (e) {
      dashMsg.textContent = "启动失败：" + e;
    }
  });

  btnStop.addEventListener("click", async () => {
    dashMsg.textContent = "正在停止 Miner...";
    try {
      const resp = await fetch("/api/stop", { method: "POST" });
      const data = await resp.json();
      if (!data.ok) {
        dashMsg.textContent = data.error || "停止失败";
        return;
      }
      dashMsg.textContent = "Miner 已停止";
      await refreshAll();
    } catch (e) {
      dashMsg.textContent = "停止失败：" + e;
    }
  });

  btnRefresh.addEventListener("click", () => {
    dashMsg.textContent = "正在刷新状态...";
    refreshAll().then(() => {
      dashMsg.textContent = "已刷新";
      setTimeout(() => (dashMsg.textContent = ""), 1500);
    });
  });

  // ================== 定时刷新 ==================

  refreshAll();
  setInterval(refreshAll, 15_000); // 每 15 秒刷新一次
});
