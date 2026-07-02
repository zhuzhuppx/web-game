# 🎮 Web Game Hub

纯前端游戏大厅，所有游戏零依赖、单文件 HTML+CSS+JS 实现。

## 已上线游戏

| 游戏 | 目录 | 说明 |
|------|------|------|
| 🐍 贪吃蛇 | `snake/` | 渐变蛇身、粒子特效、速度递增、手机触控 |
| 🧱 俄罗斯方块 | `tetris/` | 7种方块、等级加速、下一个预览、D-pad |
| 💣 扫雷 | `minesweeper/` | 三档难度、右键标旗、长按手机标旗、双击快速展开 |
| 🔢 2048 | `2048/` | CSS Grid 渲染、最高分持久化 |
| 🐦 Flappy Bird | `flappy/` | Canvas 物理引擎、管道碰撞、分数持久化 |
| 👻 吃豆人 | `pacman/` | 经典迷宫、4鬼AI、大力丸反击 |
| 🧩 数独 | `sudoku/` | 四档难度、求解器生成、笔记模式 |

## 在线体验

👉 [game.2u1.cn](https://game.2u1.cn)

## 本地运行

```bash
python3 -m http.server 8656 -d .
# 浏览器打开 http://localhost:8656
```

或使用任意 HTTP 服务器指向项目根目录即可。
