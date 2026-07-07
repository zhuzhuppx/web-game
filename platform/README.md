# 🎮 AI 游戏工坊

> 用对话创造游戏，不写一行代码。

[studio.2u1.cn](https://studio.2u1.cn)

## 怎么玩

1. **注册/登录**
2. **描述你想做的游戏** — "做个打砖块" "做个飞机大战"
3. **AI 五步引导** — 主角→目标→挑战→操作→音乐，一步步问清楚
4. **实时预览** — 代码即时在右侧可玩
5. **继续迭代** — "加点特效" "太难了改简单"
6. **保存分享** — 一键分享链接，朋友无需登录就能玩

## 五步设计法

AI 不会直接堆代码，而是先问清五个问题再动手：

| 步 | 问题 | 示例 |
|----|------|------|
| 🦸 主角 | 谁是你的角色？ | 一只会飞的猫 |
| 🏆 目标 | 玩家要达成什么？ | 躲开障碍飞到终点 |
| ⚡ 挑战 | 怎样变难？ | 障碍越来越快 |
| 🎮 操作 | 怎么控制？ | WASD 移动，空格跳 |
| 🎵 音乐 | BGM 风格？ | 欢快 8-bit |

## 架构

```
浏览器
  │
  ├─→ Express (:8765) ──→ SQLite
  │     ├─→ /api/chat  ──→ DeepSeek V4 Flash
  │     └─→ /api/speech ──→ faster-whisper (:8766, GPU)
  │
  └─→ nginx → frpc → 公网
```

## 项目结构

```
├── app/                 # 主应用
│   ├── Dockerfile
│   ├── server.js        # Express 后端
│   ├── package.json
│   └── public/          # 前端
│       ├── workspace.html
│       ├── login.html
│       ├── admin.html
│       └── sfx.js       # 音效引擎
├── speech/              # 语音识别
│   ├── Dockerfile
│   └── speech.py        # faster-whisper
├── data/                # SQLite 持久化
├── docker-compose.yml   # 容器编排
├── start.sh             # 本地开发一键启动
└── README.md
```

## 核心功能

- 🎤 **语音输入** — 浏览器录音 → Whisper GPU 推理 → 自动填入发送
- 🔊 **音效系统** — 21 种音效 + 4 种 BGM，纯 Web Audio 合成，零依赖
- 🔗 **分享链接** — `/play/{用户码}/{游戏码}`，无需登录，禁用缓存
- 🔐 **多用户** — 账户名注册，密钥由用户浏览器管理，服务端不留存
- 💾 **SQLite + WAL** — 原子写入，bind mount 持久化

## 本地开发

```bash
# 主服务
cd app && npm install && node server.js

# 语音服务（需 NVIDIA GPU）
cd speech && pip install faster-whisper flask && python3 speech.py

# 或一键
./start.sh
```

## Docker 部署

```bash
# 一键启动全部服务
docker compose up -d

# 单独启动
docker compose up -d web
docker compose up -d speech
```

> 语音服务需 nvidia-container-toolkit。如果不需要语音，注释掉 `speech` 段落即可。

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `ADMIN_PASSWORD` | `admin123` | 管理后台密码 |
| `WHISPER_MODEL` | `base` | Whisper 模型尺寸 |
| `WHISPER_CACHE` | 默认 | 模型缓存路径 |

## 技术栈

前端：原生 HTML/CSS/JS · 后端：Node.js + Express 5 · 数据库：SQLite (better-sqlite3) · AI：DeepSeek V4 Flash · 语音：faster-whisper + CTranslate2 + CUDA · 音效：Web Audio API · 部署：Docker + nginx + frpc

## 设计约束

代码上限 200 行 · 每轮最多 15 轮对话 · API 超时 120s · max_tokens 8192 · AI 回复完整显示含代码块 · `textContent` 防 XSS · 四层代码提取兜底
