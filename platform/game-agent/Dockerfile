FROM python:3.11-slim

WORKDIR /app

# 安装 Playwright 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libu2f-udev \
    libvulkan1 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY server.py start.sh ./
RUN mkdir -p games

# 创建非 root 用户运行
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app

# 以 appuser 身份安装 Playwright Chromium（确保浏览器可访问）
USER appuser
RUN python3 -m playwright install chromium
USER appuser

EXPOSE 8764

ENV GAME_AGENT_MODEL=deepseek

CMD ["python3", "server.py", "--port", "8764", "--model", "deepseek"]