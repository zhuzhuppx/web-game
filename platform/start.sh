#!/bin/bash
cd /home/ppx/.qwenpaw/workspaces/D2GPcF/www/platform
export ADMIN_PASSWORD=admin123
fuser -k 8765/tcp 2>/dev/null
sleep 1
nohup node server.js > /tmp/platform.log 2>&1 &
echo "平台启动于 PID: $! → http://localhost:8765"