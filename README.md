# 🎮 Web Game Hub

纯前端游戏大厅，所有游戏单文件 HTML+CSS+JS 实现，部分游戏使用 Phaser 3 引擎。

## 🕹️ 游戏列表（17 款）

| 游戏 | 目录 | 类型 | 说明 |
|------|------|------|------|
| 🐍 贪吃蛇 | `snake/` | 休闲 | 渐变蛇身、粒子特效、速度递增、触控 |
| 🧱 俄罗斯方块 | `tetris/` | 经典 | 7种方块、消行动画、音效、等级加速 |
| 💣 扫雷 | `minesweeper/` | 策略 | 三档难度、右键标旗、双击快速展开 |
| 🔢 2048 | `2048/` | 休闲 | CSS Grid 渲染、最高分持久化 |
| 🐦 Flappy Bird | `flappy/` | 动作 | Canvas 物理、管道碰撞、手机点击 |
| 👻 吃豆人 | `pacman/` | 经典 | 经典迷宫、4鬼AI、大力丸反击 |
| 🧩 数独 | `sudoku/` | 益智 | 四档难度、求解器生成、笔记模式 |
| ⭕ 井字棋 | `tictactoe/` | 对战 | 双人对战、AI 随机 |
| 🔴 四子棋 | `connect4/` | 策略 | 竖落棋子、四子连珠 |
| 🧠 记忆翻牌 | `memory/` | 记忆 | 配对翻牌、步数计时 |
| 🔨 打地鼠 | `whack/` | 反应 | 限时打地鼠、分数榜 |
| 🧱 打砖块 | `brick/` | 动作 | 鼠标/触屏控制挡板、关卡递增 |
| 🦘 涂鸦跳跃 | `doodle/` | 动作 | 无限跳板、随机生成 |
| 🚀 太空射击 | `space/` | 射击 | 战斗机、武器升级、多种外星人、Boss |
| ♟️ 中国象棋 | `chess/` | 策略 | Phaser 引擎、Pikafish AI、开局库 |
| 🃏 斗地主 | `poker/` | 牌类 | Phaser 引擎、AI 陪玩 |
| ⚔️ 红警·冲突 | `rts/` | 战略 | 即时战略、造兵采矿、摧毁敌方基地 |

## 🧠 中国象棋 AI

象棋使用 [Pikafish](https://github.com/Pikafish/Pikafish) NNUE 引擎作为 AI 对手，通过 Java HTTP 服务代理 UCI 协议。

服务端代码放在 `chess/ChessProxy.java`，启动脚本 `chess/run.sh`。

**部署步骤：**
1. 下载 Pikafish 二进制到 `pikafish_data/` 目录
2. 编译：`javac ChessProxy.java`
3. 启动：`./run.sh`（监听 8656 端口，同时提供静态文件服务）

## 在线体验

👉 [game.2u1.cn](https://game.2u1.cn)

## 本地运行（纯前端游戏）

```bash
python3 -m http.server 8656 -d .
# 浏览器打开 http://localhost:8656
```

## 技术栈

- **纯 Canvas** — 贪吃蛇、俄罗斯方块、扫雷、2048、Flappy Bird、吃豆人等
- **Phaser 3** — 斗地主、中国象棋（游戏引擎版）
- **Java** — 象棋 Pikafish AI 代理服务
- **Web Audio API** — 通用音效系统（`sfx.js`）

## 开发

所有游戏由 AI（DeepSeek + QwenPaw）通过对话生成。对话即开发，无手工编码。

🐒 老猿人 · [GitHub](https://github.com/zhuzhuppx/web-game)
