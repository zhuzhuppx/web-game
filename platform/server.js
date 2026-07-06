// DeepSeek proxy for AI 游戏工坊
const http = require('http');
const https = require('https');

const DEEPSEEK_KEY = process.env.DEEPSEEK_API_KEY_GAME;
const MODEL = 'deepseek-chat';
const PORT = 8765;

const SYSTEM_PROMPT = `你是"游戏工坊"的AI助手，专门帮儿童设计和开发网页小游戏。

你的规则：
1. 只能做游戏相关的事。如果有人问其他问题，回复："我只会做游戏哦～说说你想做什么游戏吧！"
2. 游戏必须是单文件 HTML（含 CSS + Canvas JS），直接输出完整代码
3. 每次回复控制在合理长度（游戏代码不超过 300 行）
4. 先确认需求再写代码。用简单的话跟小孩沟通
5. 代码里不要用外部依赖，纯 HTML+Canvas
6. 回复格式：先简短确认理解（一句话），然后用 \`\`\`html ... \`\`\` 包裹完整游戏代码
7. 如果小孩要修改，只输出修改后的完整文件，不要只给 diff
8. 游戏要能玩、要有分数/输赢条件
9. 保持鼓励的语气，多夸小孩的想法
10. 每次对话控制在 10 轮以内，到了提醒"今天做得很棒了！"`;

function callDeepSeek(messages) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({
      model: MODEL,
      messages: [
        { role: 'system', content: SYSTEM_PROMPT },
        ...messages
      ],
      max_tokens: 4096,
      temperature: 0.7
    });

    const req = https.request({
      hostname: 'api.deepseek.com',
      path: '/v1/chat/completions',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${DEEPSEEK_KEY}`,
        'Content-Length': Buffer.byteLength(body)
      },
      timeout: 30000
    }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          const json = JSON.parse(data);
          if (json.error) {
            reject(new Error(json.error.message || 'API error'));
            return;
          }
          resolve(json.choices[0].message.content);
        } catch (e) {
          reject(new Error('Parse error: ' + data.slice(0, 200)));
        }
      });
    });

    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('Timeout')); });
    req.write(body);
    req.end();
  });
}

const server = http.createServer(async (req, res) => {
  // CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(200);
    res.end();
    return;
  }

  if (req.method !== 'POST' || req.url !== '/chat') {
    res.writeHead(404);
    res.end('Not Found');
    return;
  }

  let body = '';
  req.on('data', chunk => body += chunk);
  req.on('end', async () => {
    try {
      const { messages } = JSON.parse(body);
      if (!messages || !Array.isArray(messages)) {
        throw new Error('Invalid messages');
      }

      console.log(`[chat] ${messages.length} messages, last: "${(messages[messages.length-1]?.content||'').slice(0,50)}"`);
      const reply = await callDeepSeek(messages);
      console.log(`[reply] ${reply.slice(0,80)}...`);

      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ reply }));
    } catch (e) {
      console.error('[error]', e.message);
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: e.message }));
    }
  });
});

server.listen(PORT, () => {
  console.log(`游戏工坊 API 代理运行在 http://localhost:${PORT}/chat`);
});
