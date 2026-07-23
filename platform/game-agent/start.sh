#!/bin/bash
# 启动游戏开发 Agent 服务
# 用法: ./start.sh [port] [model]

PORT=${1:-8080}
MODEL=${2:-local}

cd "$(dirname "$0")"

# 使用 venv 的 Python
PYTHON="/home/ppx/.qwenpaw/venv/bin/python3"

# 如果需要 API key，从这里设置
# export DASHSCOPE_API_KEY="sk-xxx"
# export DEEPSEEK_API_KEY="sk-xxx"

echo "🚀 启动游戏开发 Agent..."
echo "   端口: $PORT"
echo "   模型: $MODEL"

$PYTHON server.py --port "$PORT" --model "$MODEL"