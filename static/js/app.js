// static/js/app.js
let hashrateChart = null;

async function api(path, options) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  const text = await resp.text();
  let data = null;

  try {
    data = text ? JSON.parse(text) : {};
  } catch (e) {
    console.error("api() 收到非 JSON 响应:", text);

    return {
      ok: false,
      error: `服务器返回非 JSON 响应 (HTTP ${resp.status})，可能是 500 错误或反向代理拦截。`,
      raw: text,
      status: resp.status,
    };
  }

  if (typeof data === "object" && data !== null) {
    if (!("ok" in data)) {
      data.ok = resp.ok;
    }
    if (!("status" in data)) {
      data.status = resp.status;
    }
  }

  return data;
}

function showSetup() {
  document.getElementById("setup-section").style.display = "block";
  document.getElementById("dashboard-section").style.display = "none";
}

function showDashboard() {
  document.getElementById("setup-section").style.display = "none";
  document.getElementById("dashboard-section").style.display = "block";
}

function initHashrateChart() {
  const el = document.getElementById("hashrate-chart");
  if (!el || !window.ApexCharts) {
    console.warn("ApexCharts 未加载或元素缺失");
    return;
  }

  const options = {
    chart: {
      type: "line",
      height: 260,
      background: "transparent",
      foreColor: "#9ca3af",
      toolbar: {
        show: true,
        tools: {
          download: true,
          selection: false,
          zoom: false,
          zoomin: false,
          zoomout: false,
          pan: false,
          reset: false,
        },
        export: {
          csv: { filename: "scash-hashrate" },
          svg: { filename: "scash-hashrate" },
          png: { filename: "scash-hashrate" },
        },
      },
    },
    stroke: {
      curve: "smooth",
      width: 2,
    },
    dataLabels: { enabled: false },
    xaxis: {
      type: "datetime",
      labels: {
        datetimeUTC: false,
      },
    },
    yaxis: {
      labels: {
        formatter: function (val) {
          if (!val) return "0";
          const kh = val / 1000.0;
          return kh.toFixed(2) + " KH/s";
        },
      },
    },
    series: [
      { name: "当前算力 (Raw)", data: [] },
      { name: "平滑算力 (EWMA)", data: [] },
    ],
    tooltip: {
      x: { format: "MM/dd HH:mm" },
      y: {
        formatter: function (val) {
          return (val || 0).toFixed(2) + " H/s";
        },
      },
    },
  };

  hashrateChart = new ApexCharts(el, options);
  hashrateChart.render();
}

async function refreshChart() {
  if (!hashrateChart) return;
  try {
    const data = await api("/api/hashrate-history");
    if (!data || !data.ok) return;

    const points = data.points || [];
    const rawSeries = points.map((p) => [p.ts * 1000, p.hs]);
    const ewmaSeries = points.map((p) => [p.ts * 1000, p.ewma_hs]);

    hashrateChart.updateSeries([
      { name: "当前算力 (Raw)", data: rawSeries },
      { name: "平滑算力 (EWMA)", data: ewmaSeries },
    ]);
  } catch (e) {
    console.error("刷新算力曲线失败", e);
  }
}

async function refreshStatus(showMsg) {
  try {
    const data = await api("/api/status");
    if (data.needs_setup) {
      showSetup();
    } else {
      showDashboard();
    }

    if (!data.needs_setup) {
      const running = data.running;
      document.getElementById("status-text").textContent = running ? "正在运行" : "已停止";
      const badge = document.getElementById("status-badge");
      if (running) {
        badge.classList.remove("off");
      } else {
        badge.classList.add("off");
      }

      document.getElementById("wallet").textContent = data.wallet || "-";
      document.getElementById("pool-url").textContent = data.pool_url || "-";
      document.getElementById("threads").textContent = data.threads ?? "-";
      document.getElementById("bin-path").textContent = data.bin_path || "-";
      document.getElementById("algo").textContent = data.algorithm || "-";
      document.getElementById("restart-count").textContent = data.restart_count ?? 0;
      document.getElementById("restart-delay").textContent = data.restart_delay ?? "-";
      document.getElementById("impl-text").textContent = data.impl || "-";

      document.getElementById("hashrate").textContent = data.hashrate || "未知";
      if (data.hashrate_hs) {
        document.getElementById("hashrate-hs").textContent = Number(data.hashrate_hs).toFixed(2);
      } else {
        document.getElementById("hashrate-hs").textContent = "-";
      }

      document.getElementById("hashrate-avg").textContent = data.hashrate_avg || "-";
      document.getElementById("hashrate-ewma").textContent = data.hashrate_ewma || "-";
      document.getElementById("last-submit").textContent = data.last_submit || "-";

      if (showMsg) {
        const msg = document.getElementById("dash-msg");
        msg.textContent = "状态已更新";
        setTimeout(() => (msg.textContent = ""), 1500);
      }
    }
  } catch (err) {
    console.error(err);
  }
}

async function refreshLogs() {
  try {
    const data = await api("/api/logs");
    const box = document.getElementById("log-box");

    if (!data || data.error) {
      box.textContent = (data && data.error) || "获取日志失败";
    } else {
      box.textContent = data.logs || "暂无日志...";
    }

    box.scrollTop = box.scrollHeight;
  } catch (e) {
    console.error("刷新日志失败", e);
  }
}

async function startMiner() {
  const msg = document.getElementById("dash-msg");
  msg.textContent = "正在发送启动请求...";
  msg.classList.remove("error");
  try {
    const data = await api("/api/start", { method: "POST", body: "{}" });
    if (!data.ok) {
      msg.textContent = data.error || "启动失败";
      msg.classList.add("error");
    } else {
      msg.textContent = "";
    }
    await refreshStatus(true);
    await refreshLogs();
    await refreshChart();
  } catch (err) {
    msg.textContent = "启动失败: " + err;
    msg.classList.add("error");
  }
}

async function stopMiner() {
  const msg = document.getElementById("dash-msg");
  msg.textContent = "正在发送停止请求...";
  msg.classList.remove("error");
  try {
    const data = await api("/api/stop", { method: "POST", body: "{}" });
    if (!data.ok) {
      msg.textContent = data.error || "停止失败";
      msg.classList.add("error");
    } else {
      msg.textContent = "";
    }
    await refreshStatus(true);
    await refreshLogs();
    await refreshChart();
  } catch (err) {
    msg.textContent = "停止失败: " + err;
    msg.classList.add("error");
  }
}

async function saveSetup() {
  const impl = document.getElementById("setup-impl").value;
  const wallet = document.getElementById("setup-wallet").value.trim();
  const poolSelect = document.getElementById("setup-pool");
  let pool = poolSelect.value;
  const poolCustom = document.getElementById("setup-pool-custom").value.trim();
  const threads = document.getElementById("setup-threads").value.trim();
  const binPathInput = document.getElementById("setup-bin").value.trim();
  const msg = document.getElementById("setup-msg");
  const btn = document.getElementById("btn-setup-save");

  msg.classList.remove("error");
  btn.disabled = true;

  if (!wallet) {
    msg.textContent = "请填写钱包地址。";
    msg.classList.add("error");
    btn.disabled = false;
    return;
  }

  if (pool === "custom") {
    if (!poolCustom) {
      msg.textContent = "请选择矿池或填写自定义矿池地址。";
      msg.classList.add("error");
      btn.disabled = false;
      return;
    }
    pool = poolCustom;
  }

  // pool 允许：pool.scash.pro:8888 / 8.217.27.122:7019 / stratum+tcp://...
  // 后端会根据 impl 自动补全 cpuminer 的前缀

  let threadsNum = null;
  if (threads) {
    threadsNum = parseInt(threads, 10);
    if (!threadsNum || threadsNum <= 0) {
      msg.textContent = "线程数必须是正整数。";
      msg.classList.add("error");
      btn.disabled = false;
      return;
    }
  }

  msg.textContent = "正在保存配置并启动 Miner...";
  try {
    const payload = {
      impl,
      wallet,
      pool_url: pool,
      bin_path: binPathInput || null,
    };
    if (threadsNum) payload.threads = threadsNum;

    const data = await api("/api/setup", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    if (!data.ok) {
      msg.textContent = data.error || "保存失败";
      msg.classList.add("error");
      btn.disabled = false;
      return;
    }

    msg.textContent = "保存成功，正在启动 Miner...";
    await refreshStatus(false);
    await refreshLogs();
    await refreshChart();
    showDashboard();
  } catch (err) {
    msg.textContent = "请求失败: " + err;
    msg.classList.add("error");
  } finally {
    btn.disabled = false;
  }
}

async function resetConfig() {
  const btn = document.getElementById("btn-reset");
  const oldText = btn.textContent;
  const yes = confirm("确定要清空当前配置并重新运行向导吗？矿工将被停止。");
  if (!yes) return;

  btn.disabled = true;
  btn.textContent = "正在重置向导...";

  try {
    const data = await api("/api/reset-config", { method: "POST", body: "{}" });
    if (!data.ok) {
      alert(data.error || "重置失败");
    } else {
      // 前端：清空向导里残留的内容和提示
      const wallet = document.getElementById("setup-wallet");
      const threads = document.getElementById("setup-threads");
      const binPath = document.getElementById("setup-bin");
      const poolSel = document.getElementById("setup-pool");
      const poolCustom = document.getElementById("setup-pool-custom");
      const setupMsg = document.getElementById("setup-msg");

      if (wallet) wallet.value = "";
      if (threads) threads.value = "";
      if (binPath) binPath.value = "";
      if (poolSel) poolSel.value = "pool.scash.pro:8888";
      if (poolCustom) {
        poolCustom.value = "";
        poolCustom.classList.add("hidden");
      }
      if (setupMsg) setupMsg.textContent = "";

      // 让页面回到向导视图
      await refreshStatus(false);
      await refreshLogs();
      await refreshChart();
      showSetup();
    }
  } catch (err) {
    alert("重置失败: " + err);
  } finally {
    btn.disabled = false;
    btn.textContent = oldText;
  }
}


document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("btn-start").addEventListener("click", startMiner);
  document.getElementById("btn-stop").addEventListener("click", stopMiner);
  document.getElementById("btn-refresh").addEventListener("click", () => {
    refreshStatus(true);
    refreshLogs();
    refreshChart();
  });
  document.getElementById("btn-setup-save").addEventListener("click", saveSetup);
  document.getElementById("btn-reset").addEventListener("click", resetConfig);

  document.getElementById("setup-pool").addEventListener("change", (e) => {
    const v = e.target.value;
    const custom = document.getElementById("setup-pool-custom");
    custom.classList.toggle("hidden", v !== "custom");
  });

  initHashrateChart();
  refreshStatus(false);
  refreshLogs();
  refreshChart();

  // 默认 5 秒轮询一次（状态+日志+图表）
  setInterval(() => {
    refreshStatus(false);
    refreshLogs();
    refreshChart();
  }, 5000);
});
