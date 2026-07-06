const express = require('express');
const cookieParser = require('cookie-parser');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const PORT = 8765;
const SALT = 'game-platform-salt';
const DATA_DIR = path.join(__dirname, 'data');
const GAMES_DIR = path.join(DATA_DIR, 'games');
const USERS_FILE = path.join(DATA_DIR, 'users.json');
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'admin123';

[DATA_DIR, GAMES_DIR].forEach(function(d){if(!fs.existsSync(d))fs.mkdirSync(d,{recursive:true})});
if(!fs.existsSync(USERS_FILE))fs.writeFileSync(USERS_FILE,'{}');
function readUsers(){return JSON.parse(fs.readFileSync(USERS_FILE,'utf8'))}
function writeUsers(u){fs.writeFileSync(USERS_FILE,JSON.stringify(u,null,2))}
function hash(pw){return crypto.createHash('sha256').update(pw+SALT).digest('hex')}

// 用户 → 短码（用 SHA256 前 6 位，避免中文 URL）
function userCode(name){return crypto.createHash('sha256').update('u_'+name).digest('hex').slice(0,6)}
// 游戏 ID 生成（递增）
function nextGameId(meta){var i=1;while(meta['g'+i])i++;return 'g'+i}

var app=express();
app.use(express.json({limit:'2mb'}));
app.use(cookieParser());
app.use(function(req,res,next){
  res.set('Cache-Control','no-store,no-cache,must-revalidate');
  res.set('Pragma','no-cache');
  res.set('Expires','0');
  next();
});
app.get('/', function(req,res){
  res.type('html').send(fs.readFileSync(path.resolve(__dirname,'workspace.html'),'utf8'));
});
app.get('/login', function(req,res){
  res.type('html').send(fs.readFileSync(path.join(__dirname,'login.html'),'utf8'));
});
app.get('/admin', function(req,res){
  res.type('html').send(fs.readFileSync(path.join(__dirname,'admin.html'),'utf8'));
});
app.get('/api/config', function(req,res){
  res.json({apiKey:'',notice:'请点击右上角 ⚙️ 设置你的 DeepSeek API Key'});
});
app.use('/platform', express.static(__dirname, {index: false}));

// 独立游戏播放页（分享用）— 纯英文短码 URL
app.get('/play/:ucode/:gcode',function(req,res){
  // 从 ucode 反查用户名
  var users=readUsers(),userName=null;
  Object.keys(users).forEach(function(n){if(users[n].code===req.params.ucode)userName=n});
  if(!userName)return res.status(404).send('用户不存在');
  var metaFile=path.join(GAMES_DIR,userName,'meta.json');
  if(!fs.existsSync(metaFile))return res.status(404).send('游戏不存在');
  var meta=JSON.parse(fs.readFileSync(metaFile,'utf8'));
  var info=meta[req.params.gcode];
  if(!info)return res.status(404).send('游戏不存在');
  var file=path.join(GAMES_DIR,userName,req.params.gcode+'.html');
  if(!fs.existsSync(file))return res.status(404).send('游戏不存在');
  var html=fs.readFileSync(file,'utf8');
  var title=info.title||'游戏';
  var wrapper='<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">'+
    '<meta name="viewport" content="width=device-width,initial-scale=1.0,user-scalable=no">'+
    '<title>'+title+' - AI 游戏工坊</title>'+
    '<style>*{margin:0;padding:0;box-sizing:border-box}html,body{width:100%;height:100%;overflow:hidden;background:#000}'+
    'canvas{display:block}</style></head><body>';
  res.send(html.replace(/<!DOCTYPE[^>]*>/i,'').replace(/<html[^>]*>/i,'').replace(/<\/html>/i,'').replace(/<head>[\s\S]*?<\/head>/i,function(m){
    return wrapper+m.replace(/<\/head>/i,'');
  }));
});

// 兼容旧 URL
app.get('/p/:user/:slug',function(req,res){
  var file=path.join(GAMES_DIR,req.params.user,req.params.slug+'.html');
  if(!fs.existsSync(file))return res.status(404).send('not found');
  res.sendFile(file);
});

function requireAuth(req,res,next){
  var user=req.cookies&&req.cookies.auth_token;
  if(!user)return res.status(401).json({error:'请先登录'});
  var users=readUsers();
  if(!users[user]||!users[user].active)return res.status(403).json({error:'账号无效'});
  req.userName=user;
  req.userCode=users[user].code;
  next();
}

function requireAdmin(req,res,next){
  var pass=(req.headers&&req.headers['x-admin-password'])||(req.cookies&&req.cookies.admin_pass);
  if(pass!==ADMIN_PASSWORD)return res.status(401).json({error:'管理员密码错误'});
  next();
}

app.post('/api/register',function(req,res){
  var u=req.body.username||'',p=req.body.password||'';
  u=u.trim().slice(0,20).replace(/[^a-zA-Z0-9\u4e00-\u9fa5_-]/g,'');
  if(!u||u.length<2)return res.status(400).json({error:'用户名2-20字符'});
  if(p.length<3)return res.status(400).json({error:'密码至少3位'});
  var users=readUsers();
  if(users[u])return res.status(409).json({error:'用户名已存在'});
  users[u]={pass:hash(p),active:true,code:userCode(u),created:new Date().toISOString().slice(0,10)};
  writeUsers(users);
  res.cookie('auth_token',u,{maxAge:30*24*3600*1000,httpOnly:false,sameSite:'lax'});
  res.json({ok:true,username:u,code:users[u].code});
});

app.post('/api/login',function(req,res){
  var u=(req.body.username||'').trim(),p=req.body.password||'';
  var users=readUsers();
  if(!users[u]||!users[u].active||users[u].pass!==hash(p))
    return res.status(401).json({error:'用户名或密码错误'});
  res.cookie('auth_token',u,{maxAge:30*24*3600*1000,httpOnly:false,sameSite:'lax'});
  res.json({ok:true,username:u,code:users[u].code});
});

app.post('/api/logout',function(req,res){
  res.clearCookie('auth_token');
  res.json({ok:true});
});

app.get('/api/me',function(req,res){
  var user=req.cookies&&req.cookies.auth_token;
  if(!user)return res.json({loggedIn:false});
  var users=readUsers();
  if(!users[user]||!users[user].active)return res.json({loggedIn:false});
  res.json({loggedIn:true,username:user,code:users[user].code});
});

// 旧用户迁移：没有 code 的补上
function ensureUserCode(){
  var users=readUsers(),changed=false;
  Object.keys(users).forEach(function(n){
    if(!users[n].code){users[n].code=userCode(n);changed=true}
  });
  if(changed)writeUsers(users);
}
ensureUserCode();

app.get('/api/my-games',requireAuth,listGames);
app.get('/api/games',requireAuth,listGames);
function listGames(req,res){
  var dir=path.join(GAMES_DIR,req.userName);
  if(!fs.existsSync(dir))return res.json({games:[]});
  var metaFile=path.join(dir,'meta.json');
  var meta=fs.existsSync(metaFile)?JSON.parse(fs.readFileSync(metaFile,'utf8')):{};
  var games=Object.values(meta).sort(function(a,b){return b.updated-a.updated});
  res.json({games:games,userCode:req.userCode});
}

app.post('/api/save-game',requireAuth,saveGame);
app.post('/api/save',requireAuth,saveGame);
function saveGame(req,res){
  var title=req.body.title||'',html=req.body.html||'';
  if(!title||!html)return res.status(400).json({error:'缺少参数'});
  var dir=path.join(GAMES_DIR,req.userName);
  if(!fs.existsSync(dir))fs.mkdirSync(dir,{recursive:true});
  var metaFile=path.join(dir,'meta.json');
  var meta=fs.existsSync(metaFile)?JSON.parse(fs.readFileSync(metaFile,'utf8')):{};
  // 如果已有同名游戏 → 覆盖；否则新建
  var existing=Object.values(meta).find(function(g){return g.title===title});
  var gid,ver;
  if(existing){gid=existing.id;ver=existing.ver+1}
  else{gid=nextGameId(meta);ver=1}
  meta[gid]={id:gid,title:title,ver:ver,updated:Date.now()};
  fs.writeFileSync(metaFile,JSON.stringify(meta,null,2));
  fs.writeFileSync(path.join(dir,gid+'.html'),html);
  res.json({ok:true,id:gid,ver:ver});
}

app.get('/api/load-game/:id',requireAuth,function(req,res){loadGame(req,res)});
app.get('/api/game/:id',requireAuth,function(req,res){loadGame(req,res)});
function loadGame(req,res){
  var id=req.params.id;
  var dir=path.join(GAMES_DIR,req.userName);
  var metaFile=path.join(dir,'meta.json');
  var meta=fs.existsSync(metaFile)?JSON.parse(fs.readFileSync(metaFile,'utf8')):{};
  // 按 ID 查找，或按旧 slug 兼容
  var info=meta[id];
  if(!info){info=Object.values(meta).find(function(g){return g.title===id})}
  if(!info)return res.status(404).json({error:'游戏不存在'});
  var file=path.join(dir,info.id+'.html');
  if(!fs.existsSync(file))return res.status(404).json({error:'文件丢失'});
  res.json({ok:true,html:fs.readFileSync(file,'utf8'),title:info.title,id:info.id,version:info.ver||1});
}

app.post('/api/delete-game',requireAuth,deleteGame);
app.post('/api/delete',requireAuth,deleteGame);
function deleteGame(req,res){
  var id=req.body.id||req.body.slug||req.body.title;
  if(!id)return res.status(400).json({error:'缺少参数'});
  var dir=path.join(GAMES_DIR,req.userName);
  var metaFile=path.join(dir,'meta.json');
  var meta=fs.existsSync(metaFile)?JSON.parse(fs.readFileSync(metaFile,'utf8')):{};
  var info=meta[id]||Object.values(meta).find(function(g){return g.title===id||g.id===id});
  if(!info)return res.status(404).json({error:'游戏不存在'});
  var file=path.join(dir,info.id+'.html');
  if(fs.existsSync(file))fs.unlinkSync(file);
  delete meta[info.id];
  fs.writeFileSync(metaFile,JSON.stringify(meta,null,2));
  res.json({ok:true});
}

app.post('/api/admin/login',function(req,res){
  if(req.body.password!==ADMIN_PASSWORD)return res.status(401).json({error:'密码错误'});
  res.cookie('admin_pass',req.body.password,{maxAge:8*3600*1000,httpOnly:false,sameSite:'lax'});
  res.json({ok:true});
});

app.get('/api/admin/users',requireAdmin,function(req,res){
  var users=readUsers(),result=[];
  Object.keys(users).forEach(function(name){
    var u=users[name];
    var dir=path.join(GAMES_DIR,name);
    var meta=fs.existsSync(path.join(dir,'meta.json'))?JSON.parse(fs.readFileSync(path.join(dir,'meta.json'),'utf8')):{};
    result.push({username:name,code:u.code,active:u.active,created:u.created,gameCount:Object.keys(meta).length});
  });
  res.json({users:result});
});

app.post('/api/admin/toggle-user',requireAdmin,function(req,res){
  var username=req.body.username;
  var users=readUsers();
  if(!users[username])return res.status(404).json({error:'用户不存在'});
  users[username].active=!users[username].active;
  writeUsers(users);
  res.json({ok:true,active:users[username].active});
});

app.get('/api/stats',requireAdmin,function(req,res){
  var users=readUsers(),totalGames=0;
  Object.keys(users).forEach(function(name){
    var dir=path.join(GAMES_DIR,name);
    var meta=fs.existsSync(path.join(dir,'meta.json'))?JSON.parse(fs.readFileSync(path.join(dir,'meta.json'),'utf8')):{};
    totalGames+=Object.keys(meta).length;
  });
  res.json({userCount:Object.keys(users).length,gameCount:totalGames,activeUsers:Object.values(users).filter(function(u){return u.active}).length});
});

app.listen(PORT,function(){
  console.log('AI 游戏工坊: http://studio.2u1.cn ← http://localhost:'+PORT);
});
