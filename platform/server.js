const express = require('express');
const cookieParser = require('cookie-parser');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const PORT = 8765;
const DATA_DIR = path.join(__dirname, 'data');
const GAMES_DIR = path.join(DATA_DIR, 'games');
const USERS_FILE = path.join(DATA_DIR, 'users.json');
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'admin123';

// Ensure directories exist
[DATA_DIR, GAMES_DIR].forEach(d => { if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true }); });
if (!fs.existsSync(USERS_FILE)) fs.writeFileSync(USERS_FILE, '{}');
function readUsers() { return JSON.parse(fs.readFileSync(USERS_FILE, 'utf8')); }
function writeUsers(u) { fs.writeFileSync(USERS_FILE, JSON.stringify(u, null, 2)); }

const app = express();
app.use(express.json({ limit: '2mb' }));
app.use(cookieParser());

// ========== STATIC ==========
app.use('/platform', express.static(__dirname));

// Serve saved games
app.get('/p/:code/:slug', (req, res) => {
  const file = path.join(GAMES_DIR, req.params.code, req.params.slug + '.html');
  if (!fs.existsSync(file)) return res.status(404).send('游戏不存在');
  res.sendFile(file);
});

// ========== AUTH MIDDLEWARE ==========
function requireCode(req, res, next) {
  const code = req.cookies?.invite_code;
  if (!code) return res.status(401).json({ error: '请先输入邀请码' });
  const users = readUsers();
  if (!users[code] || !users[code].active) return res.status(403).json({ error: '邀请码无效或已禁用' });
  req.userCode = code;
  req.userName = users[code].name;
  next();
}

function requireAdmin(req, res, next) {
  const pass = req.headers['x-admin-password'] || req.cookies?.admin_password;
  if (pass !== ADMIN_PASSWORD) return res.status(401).json({ error: '管理员密码错误' });
  next();
}

// ========== USER API ==========
app.post('/api/join', (req, res) => {
  const { code } = req.body;
  const users = readUsers();
  if (!users[code]) return res.status(404).json({ error: '邀请码不存在' });
  if (!users[code].active) return res.status(403).json({ error: '该账号已被禁用' });
  res.cookie('invite_code', code, { maxAge: 30 * 24 * 3600 * 1000, httpOnly: false, sameSite: 'lax' });
  res.json({ ok: true, name: users[code].name });
});

app.get('/api/user', requireCode, (req, res) => {
  res.json({ code: req.userCode, name: req.userName });
});

// ========== GAME API ==========
app.get('/api/my-games', requireCode, (req, res) => {
  const dir = path.join(GAMES_DIR, req.userCode);
  if (!fs.existsSync(dir)) return res.json({ games: [] });
  const metaFile = path.join(dir, 'meta.json');
  const meta = fs.existsSync(metaFile) ? JSON.parse(fs.readFileSync(metaFile, 'utf8')) : {};
  const games = Object.values(meta).sort((a, b) => b.updated - a.updated);
  res.json({ games });
});

app.post('/api/save-game', requireCode, (req, res) => {
  const { slug, title, html } = req.body;
  if (!slug || !html) return res.status(400).json({ error: '缺少 slug 或 html' });
  const safeSlug = slug.replace(/[^a-zA-Z0-9_-]/g, '-').slice(0, 40);
  const dir = path.join(GAMES_DIR, req.userCode);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

  // Read meta, increment version
  const metaFile = path.join(dir, 'meta.json');
  const meta = fs.existsSync(metaFile) ? JSON.parse(fs.readFileSync(metaFile, 'utf8')) : {};
  const existing = meta[safeSlug];
  const ver = existing ? existing.ver + 1 : 1;
  meta[safeSlug] = { title: title || safeSlug, ver, slug: safeSlug, updated: Date.now() };
  fs.writeFileSync(metaFile, JSON.stringify(meta, null, 2));

  // Save HTML
  fs.writeFileSync(path.join(dir, safeSlug + '.html'), html);

  res.json({ ok: true, slug: safeSlug, ver });
});

app.get('/api/load-game/:slug', requireCode, (req, res) => {
  const file = path.join(GAMES_DIR, req.userCode, req.params.slug + '.html');
  if (!fs.existsSync(file)) return res.status(404).json({ error: '游戏不存在' });
  res.json({ html: fs.readFileSync(file, 'utf8') });
});

app.post('/api/delete-game', requireCode, (req, res) => {
  const { slug } = req.body;
  if (!slug) return res.status(400).json({ error: '缺少 slug' });
  const dir = path.join(GAMES_DIR, req.userCode);
  const file = path.join(dir, slug + '.html');
  if (fs.existsSync(file)) fs.unlinkSync(file);
  const metaFile = path.join(dir, 'meta.json');
  if (fs.existsSync(metaFile)) {
    const meta = JSON.parse(fs.readFileSync(metaFile, 'utf8'));
    delete meta[slug];
    fs.writeFileSync(metaFile, JSON.stringify(meta, null, 2));
  }
  res.json({ ok: true });
});

// ========== ADMIN API ==========
app.post('/api/admin/login', (req, res) => {
  const { password } = req.body;
  if (password !== ADMIN_PASSWORD) return res.status(401).json({ error: '密码错误' });
  res.cookie('admin_password', password, { maxAge: 8 * 3600 * 1000, httpOnly: false, sameSite: 'lax' });
  res.json({ ok: true });
});

app.post('/api/create-invite', requireAdmin, (req, res) => {
  const { name } = req.body;
  if (!name) return res.status(400).json({ error: '请输入姓名' });
  const users = readUsers();
  let code;
  do { code = crypto.randomBytes(3).toString('hex'); } while (users[code]);
  users[code] = { name, active: true, created: new Date().toISOString().slice(0, 10) };
  writeUsers(users);
  res.json({ code, name, url: `/platform/?code=${code}` });
});

app.get('/api/admin/users', requireAdmin, (req, res) => {
  const users = readUsers();
  const result = [];
  for (const [code, u] of Object.entries(users)) {
    const dir = path.join(GAMES_DIR, code);
    const meta = fs.existsSync(path.join(dir, 'meta.json'))
      ? JSON.parse(fs.readFileSync(path.join(dir, 'meta.json'), 'utf8')) : {};
    result.push({ code, name: u.name, active: u.active, created: u.created, gameCount: Object.keys(meta).length });
  }
  res.json({ users: result });
});

app.post('/api/admin/toggle-user', requireAdmin, (req, res) => {
  const { code } = req.body;
  const users = readUsers();
  if (!users[code]) return res.status(404).json({ error: '用户不存在' });
  users[code].active = !users[code].active;
  writeUsers(users);
  res.json({ ok: true, active: users[code].active });
});

app.get('/api/stats', requireAdmin, (req, res) => {
  const users = readUsers();
  let totalGames = 0;
  for (const code of Object.keys(users)) {
    const dir = path.join(GAMES_DIR, code);
    const meta = fs.existsSync(path.join(dir, 'meta.json'))
      ? JSON.parse(fs.readFileSync(path.join(dir, 'meta.json'), 'utf8')) : {};
    totalGames += Object.keys(meta).length;
  }
  res.json({ userCount: Object.keys(users).length, gameCount: totalGames, activeUsers: Object.values(users).filter(u => u.active).length });
});

app.listen(PORT, () => {
  console.log(`🎮 游戏工坊运行在 http://localhost:${PORT}`);
  console.log(`   平台: http://localhost:${PORT}/platform/`);
  console.log(`   管理: http://localhost:${PORT}/platform/admin.html`);
});
