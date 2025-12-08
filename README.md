# SCASH Manager


轻量级 **SCASH 挖矿管家**：一键 Docker 部署，集成 Web 控制台 + Watchdog，看门狗自动拉起 Miner，前端支持现代 Web3 / 区块链风格界面。
<img width="1802" height="1158" alt="image" src="https://github.com/user-attachments/assets/9f9a8b0e-8fd7-4ddf-8aa3-583538b0eca1" />
<img width="2880" height="1462" alt="image" src="https://github.com/user-attachments/assets/95e0e286-783b-4ebb-aeae-681fff6000c4" />


> 当前支持：`cpuminer-scash` 与 `SRBMiner-MULTI`（RandomSCASH / RandomX-SCASH），XMRig。
找我可以在https://t.me/+vsa1TnPuAaphM2U1
---

## 功能特性

- ✅ Web 控制台：浏览器中一键启动 / 停止 Miner
- ✅ 首次向导：填钱包 + 矿池地址即可开挖
- ✅ Watchdog 看门狗：
  - Miner 异常退出自动重启
  - 前端手动“停止”后不再自动拉起
- ✅ 实时日志：
  - Web 实时查看 Miner 输出
  - 自动清理 ANSI 颜色码
- ✅ 算力统计：
  - 从 Miner 日志中解析 H/s
  - 记录最近 24h 的算力曲线（含 EWMA 平滑）
- ✅ Docker 开箱即用：
  - `Dockerfile` 已准备好
  - `/data/config.json` 挂载保存配置
- ✅ 自定义 Miner：
  - 支持自定义二进制路径
  - 支持自定义线程数

---

## 项目结构

```text
scash-manager/
├── Dockerfile
├── requirements.txt
├── README.md
├── LICENSE
├── scash_manager/
│   ├── __init__.py
│   ├── config.py
│   ├── miner.py
│   ├── miner_downloader.py
│   ├── watchdog.py
│   ├── webapp.py
│   └── utils.py
├── templates/
│   └── index.html
└── static/
    ├── css/
    │   └── style.css
    ├── js/
    │   └── app.js
    └── img/
        └── logo.svg
## 构建镜像
git clone https://github.com/syl19880203/scash-manager.git
cd scash-manager
docker build -t scash-manager:latest .

## 启动容器
mkdir -p /opt/scash-manager-data

docker run -d \
  --name scash-manager \
  -p 8080:8080 \
  -v /opt/scash-manager-data:/data \
  scash-manager:latest


## 启动后访问：

浏览器打开：http://服务器IP:8080

首次会进入配置向导，填入：

SCASH 钱包地址：scash1...

矿池：例如 pool.scash.pro:8888

线程数：留空则自动 = CPU 核数 - 1

Miner 可执行文件路径：可留空（默认：

cpuminer: /usr/local/bin/minerd

SRBMiner: /opt/SRBMiner-Multi/SRBMiner-MULTI）




## Watchdog 说明

Miner 由 Miner 类管理，Watchdog 周期性检查进程健康状态

如果 Miner 非正常退出、且不是前端手动 stop：

Watchdog 会延时一段时间自动重新启动

如果是前端在 Web 上点击【停止 Miner】：

Miner 会设置 _manual_stop_flag = True

Watchdog 检测到后 不会再自动重启


## 贡献
欢迎提交Issue/PR
1、新功能建议
2、BUG修复
3、矿池兼容性\新Miner支持
4、UI风格优化


##捐赠\打赏
如果这个项目对您有帮助，可以考虑打赏一点SCASH支持开发
scash1qdvdy4ea0v6dpw6kxnxgffsr2h3tsgf0f55z589


scash-manager

Project Structure

scash-manager/
├── Dockerfile
├── requirements.txt
├── README.md
├── LICENSE
├── scash_manager/
│   ├── __init__.py
│   ├── config.py
│   ├── miner.py
│   ├── miner_downloader.py
│   ├── watchdog.py
│   ├── webapp.py
│   └── utils.py
├── templates/
│   └── index.html
└── static/
    ├── css/
    │   └── style.css
    ├── js/
    │   └── app.js
    └── img/
        └── logo.svg
# Build and Run
Build Docker Image
First, clone the repository and build the Docker image:

Bash

git clone https://github.com/syl19880203/scash-manager.git
cd scash-manager
docker build -t scash-manager:latest .
Start the Container
Create a local data directory and run the container, mapping port 8080 and mounting the data volume:

Bash

mkdir -p /opt/scash-manager-data

docker run -d \
  --name scash-manager \
  -p 8080:8080 \
  -v /opt/scash-manager-data:/data \
  scash-manager:latest
# Access and Initial Setup
Access
Open your browser and navigate to:

http://Server_IP:8080
Configuration Wizard
Upon first access, you will be guided through a configuration wizard. Please fill in the following details:

SCASH Wallet Address: e.g., scash1...

Mining Pool: e.g., pool.scash.pro:8888

Number of Threads: Leave blank to automatically use CPU Cores - 1.

Miner Executable Path: Can be left blank (Default paths are:

cpuminer: /usr/local/bin/minerd

SRBMiner: /opt/SRBMiner-Multi/SRBMiner-MULTI)

⚙️ Watchdog Explanation
The Miner process is managed by the Miner class, and the Watchdog periodically checks the process health.

If the Miner exits abnormally (and was not manually stopped via the web interface), the Watchdog will automatically restart it after a delay.

If the Miner is stopped manually via the Web interface (by clicking [Stop Miner]), the Miner sets _manual_stop_flag = True. The Watchdog detects this flag and will not automatically restart the process.

# Contribution
We welcome your contributions through Issues or Pull Requests (PRs):

Suggestions for new features.

BUG fixes.

Pool compatibility/new Miner support.

UI style optimization.

# Donation / Tip
If this project has been helpful to you, please consider making a SCASH donation to support development:

SCASH Address: scash1qdvdy4ea0v6dpw6kxnxgffsr2h3tsgf0f55z589
 
