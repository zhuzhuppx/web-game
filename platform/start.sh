#!/bin/bash
set -e
cd "$(dirname "$0")"

case "${1:-all}" in
  app)
    echo "▶ 启动主服务..."
    cd app && node server.js
    ;;
  speech)
    echo "▶ 启动语音服务..."
    cd speech && python3 speech.py
    ;;
  all|*)
    echo "▶ 启动全部服务..."
    cd speech && nohup python3 speech.py > /tmp/speech.log 2>&1 &
    cd ../app && node server.js
    ;;
esac
