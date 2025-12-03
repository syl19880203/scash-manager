FROM python:3.12-bookworm

WORKDIR /app

# 安装 curl、wget、tar 等工具（下载 miner 用）
RUN apt-get update && \
    apt-get install -y curl wget tar && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# 后端程序
COPY scash_manager ./scash_manager
COPY templates ./templates
COPY static ./static
COPY requirements.txt .

# 这里 requirements.txt 里要包含 psutil
# 比如：
#   flask
#   requests
#   psutil
RUN pip install --no-cache-dir -r requirements.txt

# 配置目录（挂载）
VOLUME ["/data"]
ENV SCASH_MANAGER_CONFIG=/data/config.json

EXPOSE 8080

CMD ["python", "-m", "scash_manager.webapp"]
