# 游戏工坊 · 多用户 AI 游戏开发平台

## 启动

```bash
cd platform/
npm install
ADMIN_PASSWORD=你的密码 DEEPSEEK_API_KEY_GAME=sk-xxx node server.js
```

## 端口

- 平台: `http://localhost:8765/platform/`
- 管理: `http://localhost:8765/platform/admin.html`
- API: `http://localhost:8765/api/*`

## 外网访问

frpc 添加隧道:

```toml
[[proxies]]
name = "game-platform"
type = "tcp"
localIP = "127.0.0.1"
localPort = 8765
remotePort = 8765
```

然后访问 `http://你的域名:8765/platform/`

## 管理后台

1. 打开管理页面，输入管理员密码
2. 生成邀请码 → 复制链接发给小孩
3. 查看用户列表，禁用/启用

## 数据结构

```
data/
├── users.json           → 用户信息
└── games/
    └── 邀请码/
        ├── meta.json    → 游戏元数据
        └── slug.html    → 游戏代码
```
