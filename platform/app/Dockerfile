FROM node:20

WORKDIR /app

# ── Node.js 依赖 ──
COPY package.json package-lock.json ./
RUN npm install --omit=dev

# ── 复制代码 ──
COPY . .

EXPOSE 8765

CMD ["node", "server.js"]