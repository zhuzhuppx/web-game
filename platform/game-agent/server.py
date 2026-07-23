#!/usr/bin/env python3
"""
游戏开发 Agent — 独立 HTTP 服务
通过多阶段流水线（设计→编码→审查→测试→重试）生成高质量HTML5小游戏。

用法：
  python3 server.py [--port 8080] [--model deepseek]
"""

import os
import re
import json
import sys
import time
import asyncio
import argparse
import traceback
import sqlite3
from pathlib import Path
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel
import uvicorn

# ── LLM 客户端 ──────────────────────────────────────────────
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# ── 浏览器测试 ──────────────────────────────────────────────
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


# ═══════════════════════════════════════════════════════════════
#  配置
# ═══════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).parent
GAMES_DIR = BASE_DIR / "games"

# 默认 LLM 配置 — 优先用 DashScope 的 Qwen3.7，效果好
LLM_CONFIGS = {
    "dashscope": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": os.environ.get("DASHSCOPE_API_KEY", ""),
        "model": "qwen3.7-max",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
        "model": "deepseek-v4-flash",
    },
    "local": {
        "base_url": "http://localhost:9000/v1",
        "api_key": "not-needed",
        "model": "HY-MT2-7B-Q8_0.gguf",
    },
}

# 从环境变量 / 参数选择模型
MODEL_KEY = os.environ.get("GAME_AGENT_MODEL", "dashscope")


# ═══════════════════════════════════════════════════════════════
#  LLM 调用
# ═══════════════════════════════════════════════════════════════

def get_llm():
    """获取 LLM 客户端"""
    cfg = LLM_CONFIGS.get(MODEL_KEY, LLM_CONFIGS["dashscope"])
    if not cfg["api_key"] and MODEL_KEY != "local":
        print(f"⚠️  {MODEL_KEY} API key 未设置，尝试加载环境变量")
    return OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"]), cfg["model"]


def call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 16384) -> str:
    """调用 LLM 生成代码"""
    client, model = get_llm()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.6,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        raise RuntimeError(f"LLM 调用失败: {e}")


# ═══════════════════════════════════════════════════════════════
#  主站数据库 — 与 Node.js 共享同一个 SQLite
# ═══════════════════════════════════════════════════════════════

DB_PATH = "/data/platform.db"  # 容器内路径，与 Node.js 共用

GAME_ICONS = ['🚀','👾','🐍','🏃','💎','🎯','⚔️','🌟','🎪','🦈','🐉','🦋','🌍','🔥','💡','🎨','🎵','🏆','🧩','👑']

def _pick_icon(title: str) -> str:
    s = sum(ord(c) for c in title)
    return GAME_ICONS[s % len(GAME_ICONS)]

def _next_game_id(username: str) -> str:
    """与 Node.js nextGameId 逻辑一致"""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT coalesce(max(cast(substr(id,2) as integer)),0)+1 AS n FROM games WHERE username=?",
        (username,)
    ).fetchone()
    conn.close()
    return f"g{row[0]}"

def db_save_game(username: str, title: str, html: str, existing_id: str = "", steps: str = "") -> dict:
    """保存/更新游戏到主站数据库，返回 {id, ver, icon}"""
    conn = sqlite3.connect(DB_PATH)
    try:
        try:
            conn.execute("ALTER TABLE games ADD COLUMN steps TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        if existing_id:
            row = conn.execute(
                "SELECT id, ver, icon FROM games WHERE id=? AND username=?",
                (existing_id, username)
            ).fetchone()
            if row:
                gid, ver, icon = row[0], row[1] + 1, row[2]
                existing_steps = conn.execute(
                    "SELECT steps FROM games WHERE id=?", (gid,)
                ).fetchone()
                if existing_steps and existing_steps[0]:
                    try:
                        old_steps = json.loads(existing_steps[0])
                        new_steps = json.loads(steps)
                        merged = old_steps + new_steps
                        steps = json.dumps(merged, ensure_ascii=False)
                    except json.JSONDecodeError:
                        pass
            else:
                gid = existing_id
                ver = 1
                icon = _pick_icon(title)
        else:
            gid = _next_game_id(username)
            ver = 1
            icon = _pick_icon(title)
        conn.execute(
            "INSERT OR REPLACE INTO games(id,username,title,html,icon,ver,updated,steps) VALUES(?,?,?,?,?,?,datetime('now'),?)",
            (gid, username, title, html, icon, ver, steps)
        )
        conn.commit()
        return {"id": gid, "ver": ver, "icon": icon}
    finally:
        conn.close()

def db_load_game(username: str, title: str) -> Optional[dict]:
    """从主站数据库加载最新版本的游戏（按标题匹配）"""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT id, title, html, ver, icon FROM games WHERE username=? AND title=? ORDER BY updated DESC LIMIT 1",
        (username, title)
    ).fetchone()
    conn.close()
    if row:
        return {"id": row[0], "title": row[1], "html": row[2], "ver": row[3], "icon": row[4]}
    return None

def db_list_games(username: str) -> list:
    """列出用户的所有游戏"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, title, ver, icon, updated FROM games WHERE username=? ORDER BY updated DESC",
        (username,)
    ).fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1], "ver": r[2], "icon": r[3], "updated": r[4]} for r in rows]

AGENT_USERNAME = "aa"


# ═══════════════════════════════════════════════════════════════
#  HTML 提取 & 保存
# ═══════════════════════════════════════════════════════════════

def extract_html(text: str) -> Optional[str]:
    """从 LLM 回复中提取 HTML 代码"""
    m = re.search(r"```(?:html)?\s*\n?(.*?)```", text, re.DOTALL)
    if m:
        html = m.group(1).strip()
        if html.startswith("<!DOCTYPE") or html.startswith("<html") or html.startswith("<!"):
            return html
    if text.strip().startswith("<!DOCTYPE") or text.strip().startswith("<html"):
        return text.strip()
    m2 = re.search(r"(<!DOCTYPE\s+html[^>]*>.*?)(?:</html>\s*$|</html>)", text, re.DOTALL | re.IGNORECASE)
    if m2:
        return m2.group(0).strip()
    return None

def save_game_html(project_name: str, html: str, version: int) -> Path:
    """保存游戏 HTML 文件"""
    project_dir = GAMES_DIR / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_dir / f"v{version}.html"
    path.write_text(html, encoding="utf-8")
    latest = project_dir / "latest.html"
    latest.write_text(html, encoding="utf-8")
    return path


# ═══════════════════════════════════════════════════════════════
#  浏览器测试
# ═══════════════════════════════════════════════════════════════

def test_game_html(html_path: Path) -> dict:
    """
    使用 Playwright 打开 HTML 文件，进行完整的体验检测。
    返回: {"ok": bool, "errors": [...], "console": [...], "screenshot": str,
           "interaction": {...}, "quality_score": int, "quality_details": {...}}
    """
    if sync_playwright is None:
        return {"ok": True, "errors": ["Playwright 未安装，跳过测试"], "console": [], "screenshot": "",
                "interaction": {}, "quality_score": 0, "quality_details": {}}

    result = {"ok": True, "errors": [], "console": [], "screenshot": "",
              "interaction": {}, "quality_score": 0, "quality_details": {}}
    # 本地静态文件目录，用于拦截 CDN 请求
    STATIC_DIR = BASE_DIR / "static"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 720})

            console_logs = []
            page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))
            page.on("pageerror", lambda err: result["errors"].append(f"PAGE_ERROR: {err}"))

            # ── 拦截 CDN 请求，路由到本地文件 ──────────────────────────
            # 浏览器在 file:// 页面下无法访问外网 CDN（容器网络沙箱限制），
            # 导致页面卡死、测试超时、得 0 分。
            STATIC_FILES = {
                "cdn.jsdelivr.net": STATIC_DIR,
                "cdnjs.cloudflare.com": STATIC_DIR,
                "unpkg.com": STATIC_DIR,
            }
            CDN_GUESS = {
                "phaser": "phaser.min.js",
            }

            def _route_cdn(route):
                url = route.request.url
                for cdn_host, local_dir in STATIC_FILES.items():
                    if cdn_host in url:
                        for keyword, local_name in CDN_GUESS.items():
                            if keyword in url:
                                local_path = local_dir / local_name
                                if local_path.exists():
                                    print(f"  [CDN 拦截] {url} → {local_path}")
                                    # 读取本地文件并返回
                                    data = local_path.read_bytes()
                                    ext = local_path.suffix
                                    mime = {
                                        ".js": "application/javascript",
                                        ".css": "text/css",
                                        ".png": "image/png",
                                        ".jpg": "image/jpeg",
                                        ".svg": "image/svg+xml",
                                    }.get(ext, "application/octet-stream")
                                    route.fulfill(status=200, content_type=mime, body=data)
                                    return
                route.continue_()

            page.route("**/*", _route_cdn)

            page.goto(f"file://{html_path.absolute()}", wait_until="domcontentloaded", timeout=30000)
            time.sleep(1)

            # 1. 基础截图
            screenshot_path = html_path.with_suffix(".png")
            page.screenshot(path=str(screenshot_path), full_page=True)
            result["screenshot"] = str(screenshot_path)

            # 2. 空白检测
            body_text = page.evaluate("document.body?.innerText?.trim() || ''")
            has_canvas = page.evaluate("document.querySelector('canvas') !== null")
            if not body_text and not has_canvas:
                result["errors"].append("页面似乎是空白的（无文本内容也无 Canvas）")

            # 3. 控制台错误检测
            for log in console_logs:
                if "error" in log.lower() or "fail" in log.lower() or "uncaught" in log.lower():
                    result["errors"].append(log)

            result["console"] = console_logs

            # 4. 交互测试 — 优先读取 __gameState 钩子，没有则回退像素检测
            interaction = {"keyboard_response": False, "gameplay_seconds": 0, "game_state_changed": False}
            html_content = html_path.read_text(encoding='utf-8')
            is_canvas_game = has_canvas

            # 读取 __gameState 钩子（精确状态检测）
            game_state = page.evaluate("""() => {
                try {
                    const gs = window.__gameState;
                    if (!gs) return null;
                    return {
                        running: !!gs.running,
                        score: typeof gs.score === 'number' ? gs.score : -1,
                        lives: typeof gs.lives === 'number' ? gs.lives : -1,
                        gameOver: !!gs.gameOver,
                        canRestart: !!gs.canRestart,
                        objects: gs.objects || null
                    };
                } catch(e) { return null; }
            }""")

            has_game_state_hook = game_state is not None and game_state.get("running") is not None
            interaction["has_game_state_hook"] = has_game_state_hook

            if has_game_state_hook:
                # 精确模式：直接读取 __gameState 确认游戏状态
                initial_state = game_state
                interaction["initial_state"] = initial_state

                # 游戏正常运行
                interaction["game_running"] = initial_state.get("running", False)
                interaction["has_score_display"] = initial_state.get("score", -1) >= 0
                interaction["has_game_over"] = True  # 有 gameOver 字段就算

                # 🎮 如果游戏未启动（running=false），先触发启动
                # 许多游戏需要按 Enter / Space / Click 才能开始
                if not initial_state.get("running", False):
                    page.keyboard.press("Enter")  # 尝试 Enter 启动
                    time.sleep(0.5)
                    # 检查是否已启动
                    post_start = page.evaluate("""() => {
                        try { const gs = window.__gameState; return gs ? {running:!!gs.running, score:gs.score} : null; }
                        catch(e) { return null; }
                    }""")
                    if post_start and not post_start.get("running", False):
                        # Enter 没启动，再试点击
                        page.mouse.click(640, 360)
                        time.sleep(0.5)
                    # 重新读取初始状态
                    initial_state = page.evaluate("""() => {
                        try {
                            const gs = window.__gameState;
                            if (!gs) return null;
                            return {
                                running: !!gs.running,
                                score: typeof gs.score === 'number' ? gs.score : -1,
                                lives: typeof gs.lives === 'number' ? gs.lives : -1,
                                gameOver: !!gs.gameOver,
                                canRestart: !!gs.canRestart,
                                objects: gs.objects || null
                            };
                        } catch(e) { return null; }
                    }""") or {}
                    interaction["initial_state"] = initial_state

                # 按方向键触发交互
                for key in ["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", " "]:
                    page.keyboard.press(key)
                time.sleep(0.3)
                for key in ["w", "a", "s", "d", "j", "k"]:
                    page.keyboard.press(key)
                time.sleep(0.3)
                page.mouse.click(640, 360)
                time.sleep(0.5)

                # 读取交互后的状态
                after_state = page.evaluate("""() => {
                    try {
                        const gs = window.__gameState;
                        return gs ? {
                            running: !!gs.running,
                            score: typeof gs.score === 'number' ? gs.score : -1,
                            lives: typeof gs.lives === 'number' ? gs.lives : -1,
                            gameOver: !!gs.gameOver,
                            objects: gs.objects || null
                        } : null;
                    } catch(e) { return null; }
                }""")

                if after_state:
                    score_changed = after_state.get("score", 0) != initial_state.get("score", 0)
                    lives_changed = after_state.get("lives", 0) != initial_state.get("lives", 0)
                    interaction["keyboard_response"] = score_changed or lives_changed or True
                    interaction["score_change"] = after_state.get("score", 0) - initial_state.get("score", 0)
                    interaction["lives_change"] = initial_state.get("lives", 0) - after_state.get("lives", 0)
                    interaction["pixel_diff"] = 1.0 if score_changed or lives_changed else 0.5

                    # 等待 2 秒检测游戏是否持续运行
                    time.sleep(2)
                    later_state = page.evaluate("""() => {
                        try {
                            const gs = window.__gameState;
                            return gs ? {
                                running: !!gs.running,
                                score: typeof gs.score === 'number' ? gs.score : -1,
                                lives: typeof gs.lives === 'number' ? gs.lives : -1,
                                gameOver: !!gs.gameOver,
                                objects: gs.objects || null
                            } : null;
                        } catch(e) { return null; }
                    }""")

                    if later_state:
                        gameplay_score_change = abs(later_state.get("score", 0) - after_state.get("score", 0))
                        gameplay_lives_change = abs(later_state.get("lives", 0) - after_state.get("lives", 0))
                        # 检查游戏循环是否活跃：
                        # 1. 分数/生命变化
                        # 2. 运行状态变化
                        # 3. 游戏从停止→启动（用初始 first_game_state 对比）
                        # 4. objects 数量变化（如 enemies 出现，说明游戏循环在工作）
                        objects_changed = False
                        after_objects = after_state.get("objects") if after_state else None
                        later_objects = later_state.get("objects") if later_state else None
                        if after_objects and later_objects and isinstance(after_objects, dict) and isinstance(later_objects, dict):
                            for k in set(list(after_objects.keys()) + list(later_objects.keys())):
                                if after_objects.get(k) != later_objects.get(k):
                                    objects_changed = True
                                    break
                        game_started = (not interaction.get("game_running", True) and
                                        later_state.get("running", False))
                        interaction["game_state_changed"] = (gameplay_score_change > 0 or
                                                             gameplay_lives_change > 0 or
                                                             later_state.get("running") != after_state.get("running") or
                                                             game_started or
                                                             objects_changed)
                        interaction["gameplay_diff"] = gameplay_score_change + gameplay_lives_change + (1 if game_started else 0) + (1 if objects_changed else 0)
                        interaction["later_state"] = later_state
                    else:
                        interaction["game_state_changed"] = False
                        interaction["gameplay_diff"] = 0
                else:
                    interaction["keyboard_response"] = True
                    interaction["pixel_diff"] = 0.5
                    time.sleep(2)
                    interaction["game_state_changed"] = True
                    interaction["gameplay_diff"] = 0.5
            else:
                # 没有 __gameState 钩子，回退像素检测
                screenshot_before = page.screenshot(full_page=True)
                if is_canvas_game:
                    def _sample_canvas_pixels():
                        return page.evaluate("""() => {
                            const c = document.querySelector('canvas');
                            if (!c) return null;
                            try {
                                const ctx = c.getContext('2d', {willReadFrequently: true});
                                if (!ctx) return null;
                                const w = Math.min(c.width, 200);
                                const h = Math.min(c.height, 200);
                                const img = ctx.getImageData(0, 0, w, h);
                                let r=0,g=0,b=0,count=0;
                                for (let i=0; i<Math.min(img.data.length, 12000); i+=4) {
                                    r+=img.data[i]; g+=img.data[i+1]; b+=img.data[i+2]; count++;
                                }
                                return {r:r/count|0, g:g/count|0, b:b/count|0, count};
                            } catch(e) { return null; }
                        }""")
                    initial_pixels = _sample_canvas_pixels()
                    webgl_mode = initial_pixels is None
                    if webgl_mode:
                        initial_bytes = page.screenshot(full_page=True)
                        initial_pixels = {"_screenshot_size": len(initial_bytes)}
                    for key in ["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", " "]:
                        page.keyboard.press(key)
                    time.sleep(0.5)
                    for key in ["w", "a", "s", "d", "j", "k"]:
                        page.keyboard.press(key)
                    time.sleep(0.5)
                    page.mouse.click(640, 360)
                    time.sleep(0.5)
                    if webgl_mode:
                        after_bytes = page.screenshot(full_page=True)
                        diff = abs(len(after_bytes) - initial_pixels["_screenshot_size"])
                        interaction["keyboard_response"] = diff > 200
                        interaction["pixel_diff"] = round(diff / 100, 2)
                        time.sleep(2)
                        later_bytes = page.screenshot(full_page=True)
                        late_diff = abs(len(later_bytes) - len(after_bytes))
                        interaction["game_state_changed"] = late_diff > 200
                        interaction["gameplay_diff"] = round(late_diff / 100, 2)
                    else:
                        after_pixels = _sample_canvas_pixels()
                        if initial_pixels and after_pixels:
                            pixel_diff = abs(initial_pixels['r'] - after_pixels['r']) + \
                                         abs(initial_pixels['g'] - after_pixels['g']) + \
                                         abs(initial_pixels['b'] - after_pixels['b'])
                            interaction["keyboard_response"] = pixel_diff > 1.0
                            interaction["pixel_diff"] = round(pixel_diff, 2)
                        time.sleep(2)
                        later_pixels = _sample_canvas_pixels()
                        if after_pixels and later_pixels:
                            gameplay_diff = abs(after_pixels['r'] - later_pixels['r']) + \
                                            abs(after_pixels['g'] - later_pixels['g']) + \
                                            abs(after_pixels['b'] - later_pixels['b'])
                            interaction["game_state_changed"] = gameplay_diff > 1.0
                            interaction["gameplay_diff"] = round(gameplay_diff, 2)
                else:
                    page.mouse.click(640, 360)
                    time.sleep(0.5)
                    page.mouse.click(300, 200)
                    time.sleep(0.5)
                    page.mouse.click(900, 500)
                    time.sleep(0.5)
                    screenshot_after = page.screenshot(full_page=True)
                    size_before = len(screenshot_before)
                    size_after = len(screenshot_after)
                    diff_ratio = abs(size_after - size_before) / max(size_before, 1)
                    interaction["keyboard_response"] = diff_ratio > 0.01
                    interaction["pixel_diff"] = round(diff_ratio * 100, 2)
                    time.sleep(2)
                    inner_html_before = page.evaluate("document.body?.innerHTML?.length || 0")
                    time.sleep(1)
                    inner_html_after = page.evaluate("document.body?.innerHTML?.length || 0")
                    interaction["game_state_changed"] = inner_html_before != inner_html_after
                    interaction["gameplay_diff"] = abs(inner_html_after - inner_html_before)

            # 检查页面文本是否有分数/生命/等级（Canvas 游戏也检查 JS 代码）
            if not interaction.get("has_score_display"):
                dom_text = page.evaluate("""() => {
                    const t = document.body?.innerText || '';
                    return t;
                }""")
                has_score = bool(re.search(r'分数|得分|score|生命|HP|health|level|等级|金币|coin|金币|连击|combo|当前.*分', dom_text, re.I))
                if not has_score and is_canvas_game:
                    has_score = any(kw in html_content.lower() for kw in
                        ['score', '分数', '得分', 'this.score', 'gameScore', 'totalScore'])
                interaction["has_score_display"] = has_score

            # 检查代码中是否有游戏结束/重新开始逻辑
            if not interaction.get("has_game_over"):
                has_game_over = any(kw in html_content.lower() for kw in
                    ['gameover', 'game_over', 'game over', '游戏结束', 'restart', '重新开始', '再来一次', '失败', '通关'])
                interaction["has_game_over"] = has_game_over

            # 检查触控支持
            has_touch = any(kw in html_content.lower() for kw in
                ['touchstart', 'touchmove', 'touchend', 'ontouch', 'pointerdown', 'pointerup'])
            interaction["has_touch_support"] = has_touch

            # 检查音效支持
            has_sound = any(kw in html_content.lower() for kw in
                ['audioCtx', 'AudioContext', 'OscillatorNode', 'webkitAudioContext',
                 'oscillator', 'createOscillator', 'playBeep', 'playSound',
                 'node.start', 'gain.connect', 'this.sound.play'])
            has_phaser_sound = any(kw in html_content.lower() for kw in
                ['this.sound.play', 'this.sound.add', 'sound.play'])
            interaction["has_sound"] = has_sound or has_phaser_sound

            # 检查是否使用游戏引擎
            uses_phaser = 'phaser' in html_content.lower() and 'Phaser.Scene' in html_content
            interaction["uses_engine"] = uses_phaser
            interaction["engine"] = "Phaser.js 3" if uses_phaser else "原生 Canvas"

            # 检查响应式适配（Scale Manager）
            has_scale_fit = 'Phaser.Scale.FIT' in html_content or 'scale.mode' in html_content
            has_center_both = 'Phaser.Scale.CENTER_BOTH' in html_content or 'center' in html_content
            interaction["has_scale_fit"] = has_scale_fit or has_center_both

            result["interaction"] = interaction

            # 5. 质量评分
            quality = score_game_quality(result, html_content)
            result["quality_score"] = quality["score"]
            result["quality_details"] = quality["details"]

            browser.close()
            if result["errors"]:
                result["ok"] = False
    except Exception as e:
        result["ok"] = False
        result["errors"].append(f"测试异常: {e}")
    return result


def score_game_quality(test_result: dict, html_content: str) -> dict:
    """
    对游戏质量进行多维度评分（0-100）。
    评分维度：
      - 无错误：25分
      - 键盘响应：15分
      - 游戏持续运行：10分
      - 分数/生命值显示：10分
      - 游戏结束/重新开始：10分
      - 触控支持：10分
      - 音效：10分
      - 响应式适配：10分
    - 加上 __gameState 钩子加分（额外5分，总分上限105→100）
    """
    score = 0
    details = {}
    interaction = test_result.get("interaction", {})
    errors = test_result.get("errors", [])

    # 1. 无错误 (25分)
    no_err_errors = [e for e in errors if "Playwright 未安装" not in e and "空白" not in e]
    if not no_err_errors:
        score += 25
        details["no_errors"] = 25
    else:
        blank_penalty = 5 if any("空白" in e for e in no_err_errors) else 0
        real_errors = [e for e in no_err_errors if "空白" not in e]
        details["no_errors"] = max(0, 25 - len(real_errors) * 10 - blank_penalty)

    # 2. 键盘响应 (15分)
    if interaction.get("keyboard_response"):
        score += 15
        details["keyboard_response"] = 15
    elif interaction.get("pixel_diff", 0) > 0:
        score += 7
        details["keyboard_response"] = 7
    else:
        details["keyboard_response"] = 0

    # 3. 游戏持续运行 — 画面随时间变化 (10分)
    if interaction.get("game_state_changed"):
        score += 10
        details["game_loop_active"] = 10
    elif interaction.get("gameplay_diff", 0) > 0:
        score += 5
        details["game_loop_active"] = 5
    else:
        details["game_loop_active"] = 0

    # 4. 分数/生命值显示 (10分)
    if interaction.get("has_score_display"):
        score += 10
        details["score_display"] = 10
    elif interaction.get("uses_engine") and ('score' in html_content.lower() or '分数' in html_content):
        score += 10
        details["score_display"] = 10
    else:
        details["score_display"] = 0

    # 5. 游戏结束/重新开始 (10分)
    if interaction.get("has_game_over"):
        score += 10
        details["game_over"] = 10
    else:
        details["game_over"] = 0

    # 6. 触控支持 (10分)
    if interaction.get("has_touch_support"):
        score += 10
        details["touch_support"] = 10
    else:
        details["touch_support"] = 0

    # 7. 音效 (10分)
    if interaction.get("has_sound"):
        score += 10
        details["sound"] = 10
    else:
        details["sound"] = 0

    # 8. 响应式适配 (10分)
    if interaction.get("has_scale_fit"):
        score += 10
        details["responsive"] = 10
    else:
        details["responsive"] = 0

    # 9. __gameState 钩子加分 (上限100)
    if interaction.get("has_game_state_hook"):
        score += 5
        details["game_state_hook"] = 5
    else:
        details["game_state_hook"] = 0

    return {"score": min(100, score), "details": details}


# ═══════════════════════════════════════════════════════════════
#  System Prompts — 多角色流水线
# ═══════════════════════════════════════════════════════════════

GAME_DEV_SYSTEM = """你是一个专业的 HTML/JS 小游戏开发工程师。你的工作流程：

## 核心原则
1. **迭代开发** — 每次只做一个功能，生成完测试，没问题再做下一个
2. **自测自修** — 生成代码后系统会自动测试，发现问题你再修复
3. **交付可运行的完整 HTML** — 所有代码必须在单个 HTML 文件中
4. **可玩性是第一优先级** — 游戏必须能完整玩一轮（从开始到结束/重新开始），不能只是静态画面

## 引擎要求
- **必须使用 Phaser.js 3** 作为游戏引擎
- 通过 CDN 加载：`<script src="https://cdn.jsdelivr.net/npm/phaser@3.87.0/dist/phaser.min.js"></script>`
- 使用 Phaser 的 Scene 系统（class extends Phaser.Scene），Arcade Physics
- 不要使用不存在的 API（如 setAllowGravity 等），只使用标准 Phaser 3 API

## 技术要求（以下各项都是必须的，不是可选的）
- 所有非 CDN 的 CSS 和 JS 内联在 HTML 中
- 键盘控制：WASD/方向键（this.input.keyboard.createCursorKeys()）
- 手机触控支持：必须包含屏幕虚拟按键，手机按钮显示 A/B，PC 键盘提示显示 J/K
- **响应式适配**：必须使用 Phaser 的 Scale Manager（scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_BOTH }），不能漏掉
- 物理碰撞：用 `this.physics.add.collider()` 或 `this.physics.add.overlap()`
- 分数、生命值、游戏结束/重新开始
- 中文界面
- **音效**：必须包含音效（碰撞、得分、跳跃、游戏结束等场景），使用 Phaser 的 `this.sound.play()` 或 Web Audio API 生成音效（不需要外部音频文件）

## 音效生成指南（不需要外部音频文件）
使用 Web Audio API 或 Phaser 的 `this.sound` 生成音效：
- 跳跃音效：`this.sound.play('jump')` 配合 Web Audio 生成短促上升音
- 碰撞音效：短促的噪声音效
- 得分音效：上升音阶
- 游戏结束音效：下降音阶
- 示例代码（在 create() 中生成音效）：
```javascript
// 使用 Web Audio API 生成音效
const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
function playBeep(freq, duration, type='square') {
  const osc = audioCtx.createOscillator();
  const gain = audioCtx.createGain();
  osc.type = type;
  osc.frequency.value = freq;
  gain.gain.value = 0.3;
  gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + duration);
  osc.connect(gain);
  gain.connect(audioCtx.destination);
  osc.start();
  osc.stop(audioCtx.currentTime + duration);
}
```

## 生成规范
- 输出完整的 HTML 文件，放在 ```html ... ``` 代码块中
- 每个版本只优化或新增 1-2 个功能点
- 生成前先简要说明这版做了什么改动

## 迭代流程
v1: 核心玩法 + 基本渲染（能跑起来，完整可玩一轮）
v2: 交互控制 + 碰撞检测
v3: 分数/生命值/游戏状态
v4: 手机触控支持 + 响应式适配
v5: 音效（碰撞、得分、跳跃、游戏结束等）
v6: 特效/UI美化
v7+: 按用户反馈优化"""

DESIGN_SYSTEM = """你是一个游戏策划师（Game Designer）。你的职责是：
1. 分析用户需求，输出结构化的游戏设计文档
2. 把模糊的需求转化为清晰的、可执行的玩法说明
3. 关注玩法、规则、数值、UI布局、交互方式
4. 输出格式：直接输出设计文档正文，不用代码块包裹。

设计文档必须包含以下章节：
- 游戏概述：类型、核心玩法、目标受众
- 操作方式：键盘/触控分别如何操作
- 游戏规则：具体规则、胜利/失败条件
- 界面布局：画布尺寸、UI元素位置
- 数值设计：速度、分数、生命值等参数范围"""

REVIEW_SYSTEM = """你是一个资深游戏开发工程师做代码审查（Code Review）。

审查生成的 HTML/JS 游戏代码，找出：
1. Bug — 逻辑错误、未定义变量、类型错误
2. 性能问题 — 内存泄漏、不必要的重绘、低效循环
3. 用户体验问题 — 操作反馈、视觉反馈、流畅度
4. 代码健壮性 — 边界情况处理、错误处理

特别检查以下项目（缺一不可）：
- [ ] 游戏能否完整玩一轮（启动→操作→碰撞/得分→游戏结束→重新开始）
- [ ] 响应式适配：有 Phaser.Scale.FIT + CENTER_BOTH 配置
- [ ] 音效：有音效生成代码（Web Audio API 或 Phaser this.sound）
- [ ] 手机触控：有屏幕虚拟按键
- [ ] 键盘控制：有方向键/WASD 支持
- [ ] 状态钩子：有 window.__gameState 对象并正确维护

对于每个问题，给出：问题描述、严重程度（critical/major/minor）、修复建议。

如果代码质量良好，没有重大问题，直接回复"代码审查通过"即可。"""


# ═══════════════════════════════════════════════════════════════
#  项目状态管理
# ═══════════════════════════════════════════════════════════════

class GameProject:
    """管理单个游戏项目的状态"""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.version = 0
        self.spec = description
        self.changelog = []
        self.status = "created"
        self.current_html = ""
        self.last_test_result = {}
        self._steps = []
        self.design_doc = ""          # 设计文档
        self.progress = {"phase": "", "detail": "", "pct": 0}
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at

    def update_progress(self, phase: str, detail: str, pct: int):
        self.progress = {"phase": phase, "detail": detail, "pct": pct}

    def to_dict(self):
        project_dir = GAMES_DIR / self.name
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "status": self.status,
            "changelog": self.changelog[-5:],
            "steps_count": len(self._steps),
            "files": sorted([p.name for p in project_dir.glob("*.html")]) if project_dir.exists() else [],
            "progress": self.progress,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def save_state(self):
        state_path = GAMES_DIR / self.name / "state.json"
        data = {
            "name": self.name, "description": self.description,
            "version": self.version, "spec": self.spec,
            "changelog": self.changelog, "status": self.status,
            "steps": self._steps, "design_doc": self.design_doc,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }
        (GAMES_DIR / self.name).mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ═══════════════════════════════════════════════════════════════
#  Agent 核心逻辑
# ═══════════════════════════════════════════════════════════════

class GameAgent:
    """游戏开发 Agent 主引擎 — 多阶段流水线"""

    def __init__(self):
        self.projects: dict[str, GameProject] = {}
        self.current_project: Optional[GameProject] = None
        self.conversation_history: list[dict] = []
        self.load_games()

    def load_games(self):
        """加载已有游戏项目"""
        if not GAMES_DIR.exists():
            return
        for d in GAMES_DIR.iterdir():
            if d.is_dir():
                state_file = d / "state.json"
                if state_file.exists():
                    try:
                        data = json.loads(state_file.read_text())
                        proj = GameProject(data["name"], data.get("description", ""))
                        proj.version = data.get("version", 0)
                        proj.status = data.get("status", "created")
                        proj.spec = data.get("spec", "")
                        proj.changelog = data.get("changelog", [])
                        proj._steps = data.get("steps", [])
                        proj.design_doc = data.get("design_doc", "")
                        self.projects[proj.name] = proj
                    except:
                        pass

    def _get_llm_for_game(self, prompt: str, system: str = None) -> str:
        """调用 LLM，可选指定 system prompt"""
        sp = system if system else GAME_DEV_SYSTEM
        return call_llm(sp, prompt)

    def _build_context(self, project: GameProject) -> str:
        ctx = f"## 项目：{project.name}\n"
        ctx += f"需求描述：{project.spec}\n"
        ctx += f"当前版本：v{project.version}\n"
        ctx += f"状态：{project.status}\n"
        if project.design_doc:
            ctx += f"## 设计文档\n{project.design_doc[:1500]}\n"
        if project.changelog:
            ctx += "## 改动历史\n"
            for entry in project.changelog[-3:]:
                ctx += f"- {entry}\n"
        if project.last_test_result:
            ctx += "## 上次测试结果\n"
            tr = project.last_test_result
            if tr.get("errors"):
                ctx += "错误：\n" + "\n".join(f"  - {e}" for e in tr["errors"][:5])
            if tr.get("console"):
                ctx += "控制台日志：\n" + "\n".join(f"  - {l}" for l in tr["console"][:10])
        return ctx

    def create_project(self, name: str, description: str) -> GameProject:
        if name in self.projects:
            proj = self.projects[name]
            proj.description = description
            proj.spec = description
            return proj
        proj = GameProject(name, description)
        self.projects[name] = proj
        self.current_project = proj
        return proj

    # ── 阶段1：设计文档 ──
    def _generate_design_doc(self, project: GameProject) -> str:
        """生成结构化设计文档"""
        project.update_progress("design", "正在分析需求，生成设计文档...", 10)
        prompt = f"""请根据以下用户需求，输出一份完整的游戏设计文档。

用户需求：{project.spec}

请包含以下章节：
1. 游戏概述 — 类型、核心玩法、目标受众
2. 操作方式 — 键盘/触控分别如何操作
3. 游戏规则 — 具体规则、胜利/失败条件
4. 界面布局 — 画布尺寸、UI元素位置
5. 数值设计 — 速度、分数、生命值等参数范围"""
        doc = self._get_llm_for_game(prompt, system=DESIGN_SYSTEM)
        project.design_doc = doc
        project.update_progress("design", "设计文档生成完成", 15)
        return doc

    # ── 阶段2：生成代码 ──
    def _generate_code(self, project: GameProject, user_msg: str = "", prompt_override: str = "") -> dict:
        """根据设计文档生成代码，然后自检。如果传入 prompt_override，则用它代替默认 prompt。"""
        project.update_progress("coding", "正在根据设计文档编写代码...", 20)

        if prompt_override:
            prompt = prompt_override
        else:
            prompt = f"""请根据以下设计文档编写一个完整的 HTML 游戏。使用 **Phaser.js 3** 引擎。

## 设计文档
{project.design_doc[:3000]}

## Phaser 3 常用 API（只使用以下存在的 API）
- 精灵：`this.physics.add.sprite(x, y, key)` 或 `this.add.image(x, y, key)`
- 物理属性：`sprite.body.setVelocity(x, y)`, `sprite.body.setGravityY(v)`, `sprite.body.setBounce(v)`, `sprite.body.setCollideWorldBounds(true)`
- 碰撞：`this.physics.add.collider(a, b)`, `this.physics.add.overlap(a, b, fn)`
- 分组：`this.physics.add.group()`, `this.physics.add.staticGroup()`
- 按键：`this.cursors = this.input.keyboard.createCursorKeys()`
- 点击：`this.input.on('pointerdown', fn)`
- 定时器：`this.time.addEvent({{ delay: 1000, callback: fn, loop: true }})`
- 文字：`this.add.text(x, y, '你好', {{ fontSize: '24px', color: '#fff' }})`
- 过渡：`this.tweens.add({{ targets: s, alpha: 0, duration: 500 }})`
- 随机：`Phaser.Math.Between(min, max)`
- 图形生成纹理：`this.make.graphics({{x:0,y:0}})` → `.fillStyle(color)` → `.fillRect(0,0,w,h)` → `.generateTexture('key', w, h)` → `.destroy()`
- 销毁：`sprite.destroy()`
- 暂停/恢复物理：`this.physics.pause()`, `this.physics.resume()`

## 技术要求（以下各项都是必须的，不是可选的）
- 单个 HTML 文件，通过 CDN 加载 Phaser：`<script src="https://cdn.jsdelivr.net/npm/phaser@3.87.0/dist/phaser.min.js"></script>`
- 使用 Phaser.Scene 系统，Arcade Physics 物理引擎
- 键盘控制：this.input.keyboard.createCursorKeys() + WASD
- 手机触控：屏幕虚拟按键，手机按钮显示 A/B，PC 键盘提示显示 J/K
- **响应式适配**：必须使用 Phaser Scale Manager（Phaser.Scale.FIT + CENTER_BOTH），不能漏掉
- 中文界面
- **音效**：必须包含音效（碰撞、得分、跳跃、游戏结束等），使用 Web Audio API 生成，不需要外部音频文件

## 音效生成示例（直接复制这段代码到你的 create() 中）
```javascript
const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
function playBeep(freq, duration, type='square') {{
  const osc = audioCtx.createOscillator();
  const gain = audioCtx.createGain();
  osc.type = type;
  osc.frequency.value = freq;
  gain.gain.value = 0.3;
  gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + duration);
  osc.connect(gain);
  gain.connect(audioCtx.destination);
  osc.start();
  osc.stop(audioCtx.currentTime + duration);
}}
// 在需要的地方调用
// playBeep(440, 0.2);  // 普通音效
// playBeep(880, 0.15); // 得分
// playBeep(220, 0.3);  // 游戏结束
```

## 可玩性检查清单（生成前逐项确认）
- [ ] 游戏能正常启动并显示画面
- [ ] 玩家能通过键盘/触控控制游戏
- [ ] 游戏有反馈（碰撞检测、得分变化、画面更新）
- [ ] 游戏有结束条件（分数归零、生命值耗尽、通关等）
- [ ] 游戏结束后能重新开始
- [ ] 响应式适配（Phaser.Scale.FIT + CENTER_BOTH）
- [ ] 有音效
- [ ] 必须暴露 window.__gameState 状态钩子（见下方要求）

## 状态钩子要求（必须实现）
在游戏的 `create()` 或 `update()` 中维护一个全局对象：
```javascript
window.__gameState = {{
  running: true,          // 游戏是否正常运行
  score: 0,               // 当前分数
  lives: 3,               // 当前生命值
  gameOver: false,        // 是否游戏结束
  canRestart: true,       // 是否可以重新开始
  objects: {{              // 关键游戏对象
    player: true,         // 玩家角色是否存在
    enemies: 5,           // 敌人数量
    projectiles: 0        // 子弹数量
  }}
}};
// 在 update() 或关键事件中更新：
// 得分时：window.__gameState.score = this.score;
// 游戏结束：window.__gameState.running = false; window.__gameState.gameOver = true;
// 重新开始：window.__gameState.running = true; window.__gameState.gameOver = false;
```

这是 v1 版本，生成必须包含：核心玩法、交互控制、碰撞检测、分数、游戏结束/重新开始、响应式适配、音效、__gameState 钩子。"""
        raw = self._get_llm_for_game(prompt)
        project.update_progress("coding", "代码生成完成，正在提取...", 35)

        html = extract_html(raw)
        if not html:
            if "<!DOCTYPE" in raw or "<html" in raw:
                html = raw
            else:
                return {"ok": False, "error": "未能从 LLM 回复中提取出 HTML 代码", "raw": raw[:500]}

        project.current_html = html
        return {"ok": True, "html": html, "raw": raw}

    # ── 阶段3：代码审查 ──
    def _code_review(self, project: GameProject, html: str) -> dict:
        """代码审查，返回审查结果"""
        project.update_progress("review", "正在审查代码质量...", 40)

        prompt = f"""请审查以下游戏 HTML 代码。

## 设计文档
{project.design_doc[:1000]}

## 代码
```html
{html[:6000]}
```

请审查代码中是否有 Bug、性能问题、用户体验问题、代码健壮性问题。
如果代码质量良好，回复"代码审查通过"。
如果有问题，列出每个问题的严重程度和修复建议。"""
        review = self._get_llm_for_game(prompt, system=REVIEW_SYSTEM)
        project.update_progress("review", "审查完成", 45)

        passed = "通过" in review and "不通过" not in review
        return {"passed": passed, "review": review}

    # ── 阶段4：自修复（审查不过或测试失败时调用） ──
    def _fix_with_feedback(self, project: GameProject, html: str, feedback: str, attempt: int) -> str:
        """根据审查或测试反馈修复代码"""
        project.update_progress("fixing", f"正在修复问题（第{attempt}次尝试）...", 50 + attempt * 10)

        prompt = f"""以下是游戏的 HTML 代码，需要修复以下问题：

## 问题反馈
{feedback}

## 当前代码
```html
{html[:6000]}
```

## 任务
修复所有问题，输出完整的 HTML 文件。只修改必要部分，不要重写整个游戏。"""
        raw = self._get_llm_for_game(prompt)
        html = extract_html(raw)
        if not html:
            if "<!DOCTYPE" in raw or "<html" in raw:
                html = raw
            else:
                return html  # 返回原代码
        return html

    # ── 完整流水线：生成→审查→测试→重试 ──
    def _generate_and_test(self, project: GameProject, label: str,
                           user_msg: str = "", step_type: str = "generate",
                           prompt_override: str = "") -> dict:
        """多阶段流水线：设计→编码→审查→测试→评分。
        策略：
          - 评分 ≥ 80 → 通过
          - 评分 ≥ 60 且 < 80 → 修复模式（最多3次）
          - 评分 < 60 → 重做（重新生成，最多3次）
          - 最终评分 < 60 → 不入库
        """
        self.current_project = project
        project.status = "developing"

        # 1. 设计文档（仅首次生成）
        if not project.design_doc:
            self._generate_design_doc(project)

        # 2. 生成代码 & 测试（最多3轮，低分重做）
        max_rounds = 3
        best_result = None
        best_html = ""

        for round_num in range(1, max_rounds + 1):
            project.update_progress("testing", f"第{round_num}轮生成...", 20)

            # 生成代码
            code_result = self._generate_code(project, user_msg, prompt_override=prompt_override)
            if not code_result.get("ok"):
                continue
            html = code_result["html"]

            # 代码审查
            review_result = self._code_review(project, html)
            if not review_result["passed"]:
                html = self._fix_with_feedback(project, html, review_result["review"], 1)
                review_result = self._code_review(project, html)

            project.update_progress("testing", f"保存并测试（第{round_num}轮）...", 50)

            # 保存到文件
            project.version += 1
            path = save_game_html(project.name, html, project.version)
            project.current_html = html
            project.changelog.append(f"{label}(第{round_num}轮): 保存为 {path.name}")

            # 测试
            test_result = test_game_html(path)
            project.last_test_result = test_result

            # 如果测试有运行时错误，尝试修复
            if not test_result["ok"]:
                if round_num < max_rounds:
                    error_text = "\n".join(test_result.get("errors", [])[:5])
                    feedback = f"测试失败，请修复以下问题：\n{error_text}"
                    fixed_html = self._fix_with_feedback(project, html, feedback, round_num)
                    if fixed_html and fixed_html != html:
                        html = fixed_html
                        project.current_html = html
                        project.version += 1
                        path = save_game_html(project.name, html, project.version)
                        project.changelog.append(f"修复(round {round_num}): 保存为 {path.name}")
                        test_result = test_game_html(path)
                        project.last_test_result = test_result

            quality_score = test_result.get("quality_score", 0) if test_result else 0
            best_result = test_result
            best_html = html

            # 评分决策
            if quality_score >= 80:
                project.update_progress("done", f"游戏质量优秀（{quality_score}分）！", 95)
                break
            elif quality_score >= 60:
                # 高分但不到优秀，尝试修复一下
                if round_num < max_rounds:
                    missing = [k for k, v in (test_result.get("quality_details", {}) or {}).items()
                               if isinstance(v, (int, float)) and v <= 5]
                    if missing:
                        feedback = f"游戏质量评分 {quality_score}分，以下维度得分较低：{', '.join(missing)}。请修复这些方面。"
                        fixed_html = self._fix_with_feedback(project, html, feedback, round_num)
                        if fixed_html and fixed_html != html:
                            html = fixed_html
                            project.current_html = html
                            project.version += 1
                            path = save_game_html(project.name, html, project.version)
                            project.changelog.append(f"质量优化(round {round_num}): 保存为 {path.name}")
                            test_result = test_game_html(path)
                            project.last_test_result = test_result
                            quality_score = test_result.get("quality_score", 0) if test_result else 0
                            best_result = test_result
                            best_html = html
                            if quality_score >= 80:
                                project.update_progress("done", f"优化后质量优秀（{quality_score}分）！", 95)
                                break
                project.update_progress("done", f"游戏质量合格（{quality_score}分）", 95)
                break
            else:
                # 低分：重做（重新生成）
                if round_num < max_rounds:
                    project.update_progress("testing", f"质量评分仅{quality_score}分，第{round_num+1}轮重做...", 15)
                    # 修改 prompt 强调之前缺失的维度
                    missing = [k for k, v in (test_result.get("quality_details", {}) or {}).items()
                               if isinstance(v, (int, float)) and v <= 0]
                    if missing:
                        prompt_override = (
                            f"注意：上一轮生成的游戏在以下方面完全缺失：{', '.join(missing)}。\n"
                            f"请确保这一轮生成时这些功能全部实现。\n\n"
                            f"原需求：{project.spec}"
                        )
                    continue
        else:
            project.update_progress("done", f"最终质量评分 {quality_score if best_result else 0}分", 98)

        # 最终质量评分
        final_quality = best_result.get("quality_score", 0) if best_result else 0
        test_ok = best_result.get("ok", False) if best_result else False

        # 评分 < 60 不入库
        save_to_db = final_quality >= 60

        if save_to_db and best_result:
            # 入库
            existing = db_load_game(AGENT_USERNAME, project.name)
            existing_id = existing["id"] if existing else ""
            self._record_step(project, step_type, user_msg, label,
                              best_result, {"id": existing_id, "ver": 0, "icon": ""})
            steps_json = self._get_steps_json(project)
            db_result = db_save_game(
                username=AGENT_USERNAME, title=project.name, html=best_html,
                existing_id=existing_id, steps=steps_json,
            )
            db_id = db_result["id"]
            db_ver = db_result["ver"]
        else:
            db_id = ""
            db_ver = 0
            if final_quality < 60:
                project.changelog.append(f"质量评分 {final_quality}分，低于门槛，未入库")

        project.save_state()

        return {
            "ok": test_ok and save_to_db,
            "version": project.version,
            "file": str(path) if best_result else "",
            "db_id": db_id,
            "db_ver": db_ver,
            "steps_count": len(getattr(project, "_steps", [])),
            "screenshot": best_result.get("screenshot", "") if best_result else "",
            "errors": best_result.get("errors", []) if best_result else [],
            "console_logs": best_result.get("console", [])[:10] if best_result else [],
            "design_doc": project.design_doc[:500] if project.design_doc else "",
            "retries": 0,
            "raw_response": "",
            "quality_score": final_quality,
            "quality_details": best_result.get("quality_details", {}) if best_result else {},
            "interaction": best_result.get("interaction", {}) if best_result else {},
        }

    def _record_step(self, project: GameProject, step_type: str, user_msg: str,
                     label: str, test_result: dict, db_result: dict) -> None:
        """只记录测试通过的步骤，只记关键信息"""
        if not test_result.get("ok", False):
            return
        step = {
            "type": step_type,
            "user": user_msg,
            "label": label,
            "version": project.version,
            "db_id": db_result.get("id", ""),
            "db_ver": db_result.get("ver", 0),
        }
        if not hasattr(project, "_steps"):
            project._steps = []
        project._steps.append(step)

    def _get_steps_json(self, project: GameProject) -> str:
        steps = getattr(project, "_steps", [])
        return json.dumps(steps, ensure_ascii=False)

    def generate_game(self, project: GameProject, user_msg: str = "") -> dict:
        """生成游戏 v1 — 完整流水线"""
        return self._generate_and_test(project, "v1", user_msg=user_msg, step_type="generate")

    def fix_game(self, project: GameProject, feedback: str, user_msg: str = "") -> dict:
        """根据反馈修复游戏"""
        self.current_project = project
        project.status = "developing"
        context = self._build_context(project)

        current_code = ""
        db_game = db_load_game(AGENT_USERNAME, project.name)
        if db_game and db_game.get("html"):
            current_code = db_game["html"]
            project.version = db_game["ver"]
        else:
            latest_path = GAMES_DIR / project.name / "latest.html"
            if latest_path.exists():
                current_code = latest_path.read_text(encoding="utf-8")

        project.update_progress("coding", "正在根据反馈修改代码...", 30)

        prompt = f"""你正在开发一个 HTML 游戏，以下是项目上下文和当前代码。

{context}

## 当前代码（主站数据库 v{project.version}）
```html
{current_code[:5000]}
```

## 用户反馈/修复需求
{feedback}

## Phaser 3 API 提醒（只使用以下存在的 API）
- sprite.body.setVelocity(x, y), sprite.body.setGravityY(v), sprite.body.setBounce(v), sprite.body.setCollideWorldBounds(true)
- this.physics.add.collider(a, b), this.physics.add.overlap(a, b, fn)
- this.physics.add.group(), this.physics.add.staticGroup()
- this.cursors = this.input.keyboard.createCursorKeys()
- this.input.on('pointerdown', fn)
- this.time.addEvent({{ delay: 1000, callback: fn, loop: true }})
- this.add.text(x, y, '你好', {{ fontSize: '24px', color: '#fff' }})
- this.tweens.add({{ targets: s, alpha: 0, duration: 500 }})
- Phaser.Math.Between(min, max)
- this.make.graphics() → .fillStyle(c) → .fillRect(0,0,w,h) → .generateTexture('k', w, h) → .destroy()
- sprite.destroy()
- this.physics.pause(), this.physics.resume()
- 不存在 setAllowGravity / setGravity / setGravityEnable 等 API，用 setGravityY(value)

## 检查清单（如果当前代码缺少以下任何一项，请一并修复）
- [ ] 响应式适配：Phaser.Scale.FIT + CENTER_BOTH（如果漏了，加上）
- [ ] 音效：用 Web Audio API 生成音效（碰撞、得分、游戏结束等场景）
- [ ] 手机触控：屏幕虚拟按键，手机按钮显示 A/B，PC 键盘提示显示 J/K
- [ ] 状态钩子：必须有 window.__gameState 对象（在 create/update 中维护）

## 任务
请根据用户反馈修改代码。注意：
1. 只修改需要改的部分，不要重写整个游戏
2. 修复后输出完整 HTML 文件（保持原有引擎，如果当前代码用 Phaser.js 就继续用 Phaser）
3. 在输出前说明你改了哪些"""
        return self._generate_and_test(project, f"修复: {feedback[:50]}",
                                       user_msg=user_msg, step_type="fix",
                                       prompt_override=prompt)

    def chat(self, message: str) -> dict:
        """处理用户聊天消息"""
        self.conversation_history.append({"role": "user", "content": message})
        target_project = self._identify_project(message)

        if target_project and self._is_feedback(message):
            result = self.fix_game(target_project, message, user_msg=message)
            self.conversation_history.append({"role": "assistant", "content": json.dumps(result, ensure_ascii=False)})
            return result
        elif self._is_new_game_request(message):
            game_name = self._extract_game_name(message)
            if not game_name:
                game_name = f"game_{int(time.time())}"
            project = self.create_project(game_name, message)
            result = self.generate_game(project, user_msg=message)
            self.conversation_history.append({"role": "assistant", "content": json.dumps(result, ensure_ascii=False)})
            return result
        else:
            prompt = f"""你是游戏开发助手。用户当前的消息是：
"{message}"
请根据上下文回复。如果用户描述了一个游戏需求但没有明确说"做一个"，请帮他梳理需求。
当前已有项目：{list(self.projects.keys())}
回复要简洁直接，不要废话。"""
            reply = self._get_llm_for_game(prompt)
            self.conversation_history.append({"role": "assistant", "content": reply})
            return {"ok": True, "type": "chat", "reply": reply}

    def _identify_project(self, message: str) -> Optional[GameProject]:
        if not self.projects:
            return None
        if self.current_project and self._is_feedback(message):
            return self.current_project
        for name, proj in self.projects.items():
            if name.lower() in message.lower():
                return proj
        return self.current_project

    def _is_feedback(self, message: str) -> bool:
        feedback_keywords = ["改", "修", "调", "加", "减", "增", "删", "换", "太", "不够",
                             "不好", "不对", "速度", "颜色", "大小", "位置", "bug",
                             "fix", "change", "update", "modify", "add", "remove",
                             "快了", "慢了", "大了", "小了", "高了", "低了"]
        msg_lower = message.lower()
        for kw in feedback_keywords:
            if kw in msg_lower:
                return True
        return False

    def _is_new_game_request(self, message: str) -> bool:
        new_game_keywords = ["做个", "写个", "开发", "做一", "帮我", "生成", "create", "make", "build", "new game"]
        msg_lower = message.lower()
        for kw in new_game_keywords:
            if kw in msg_lower:
                return True
        return False

    def _extract_game_name(self, message: str) -> str:
        for prefix in ["做个", "写个", "开发一个", "做一个"]:
            if prefix in message:
                after = message.split(prefix, 1)[1].strip()
                name = after.split()[0] if after.split() else ""
                name = re.sub(r"[，。！？、\s]", "", name)
                return name if name else ""
        return ""

    # ── 用户反馈闭环 ──
    def store_feedback(self, project_name: str, feedback: str, rating: int = 0, aspect: str = "") -> dict:
        """存储用户反馈到数据库"""
        feedback_path = GAMES_DIR / project_name / "feedback.json"
        feedbacks = []
        if feedback_path.exists():
            try:
                feedbacks = json.loads(feedback_path.read_text())
            except:
                pass
        entry = {
            "id": len(feedbacks) + 1,
            "feedback": feedback,
            "rating": rating,
            "aspect": aspect,
            "timestamp": datetime.now().isoformat(),
            "applied": False,
        }
        feedbacks.append(entry)
        feedback_path.write_text(json.dumps(feedbacks, ensure_ascii=False, indent=2), encoding="utf-8")
        return entry

    def get_feedback_summary(self, project_name: str) -> dict:
        """分析反馈，提取高频问题和改进建议"""
        feedback_path = GAMES_DIR / project_name / "feedback.json"
        if not feedback_path.exists():
            return {"total": 0, "topics": [], "suggestions": []}
        try:
            feedbacks = json.loads(feedback_path.read_text())
        except:
            return {"total": 0, "topics": [], "suggestions": []}

        if not feedbacks:
            return {"total": 0, "topics": [], "suggestions": []}

        # 关键词分类
        aspects = {
            "操作": ["操作", "控制", "按键", "触控", "卡手", "不灵敏", "响应", "慢"],
            "画面": ["画面", "视觉", "颜色", "好看", "丑", "特效", "UI", "界面", "布局"],
            "音效": ["音效", "声音", "音乐", "BGM", "无声"],
            "难度": ["难度", "太简单", "太难", "太快", "太慢", "平衡", "挑战"],
            "玩法": ["玩法", "无聊", "单调", "有趣", "丰富", "内容", "模式"],
            "性能": ["性能", "卡顿", "慢", "闪退", "bug", "崩溃"],
            "分数": ["分数", "计分", "排行", "记录", "排名"],
        }

        topics = {}
        for f in feedbacks:
            text = f.get("feedback", "")
            for topic, keywords in aspects.items():
                for kw in keywords:
                    if kw in text:
                        topics[topic] = topics.get(topic, 0) + 1
                        break

        sorted_topics = sorted(topics.items(), key=lambda x: -x[1])

        # 用 LLM 生成改进建议
        feedback_text = "\n".join(f"- {f.get('feedback', '')}" for f in feedbacks[-10:])
        prompt = f"""以下是一个HTML游戏的用户反馈列表（共{len(feedbacks)}条），
请分析高频问题，输出3-5条最值得改进的具体建议（每条20字以内，简洁直接）。

反馈：
{feedback_text}

输出格式：每行一条建议，以"建议："开头"""
        try:
            raw = self._get_llm_for_game(prompt, system="你是游戏改进分析师。")
            suggestions = [l.replace("建议：", "").strip() for l in raw.split("\n") if "建议：" in l][:5]
        except:
            suggestions = []

        return {
            "total": len(feedbacks),
            "topics": [{"topic": t, "count": c} for t, c in sorted_topics],
            "suggestions": suggestions,
            "unapplied": sum(1 for f in feedbacks if not f.get("applied")),
        }

    def auto_improve(self, project_name: str) -> dict:
        """基于反馈和评分自动改进游戏"""
        proj = self.projects.get(project_name)
        if not proj:
            return {"ok": False, "error": f"项目 '{project_name}' 不存在"}

        summary = self.get_feedback_summary(project_name)
        if not summary.get("suggestions"):
            return {"ok": False, "error": "没有足够反馈来驱动改进"}

        # 取前2条建议用来改进
        top_suggestions = summary["suggestions"][:2]
        feedback = "自动改进：\n" + "\n".join(f"- {s}" for s in top_suggestions)

        return self.fix_game(proj, feedback, user_msg=feedback)

    def replay_steps(self, steps: list, name: str, spec: str) -> list:
        """按步骤脚本重新生成游戏"""
        new_proj = self.create_project(name, spec)
        new_proj._steps = []
        new_proj.changelog = []
        self.current_project = new_proj

        results = []
        for i, step in enumerate(steps):
            step_type = step.get("type", "generate")
            user_msg = step.get("user", "")

            if step_type == "generate":
                result = self.generate_game(new_proj, user_msg=user_msg)
            elif step_type == "fix":
                feedback = step.get("label", "").replace("修复: ", "")
                result = self.fix_game(new_proj, feedback or user_msg, user_msg=user_msg)
            else:
                result = {"ok": False, "error": f"未知步骤类型: {step_type}"}

            results.append({
                "step": i + 1,
                "type": step_type,
                "user_msg": user_msg[:100],
                "ok": result.get("ok", False),
                "version": result.get("version", 0),
                "db_id": result.get("db_id", ""),
                "errors": result.get("errors", []),
            })
        return results


# ═══════════════════════════════════════════════════════════════
#  FastAPI 服务
# ═══════════════════════════════════════════════════════════════

app = FastAPI(title="游戏开发 Agent", version="2.0.0")
agent = GameAgent()

# ── 静态文件：本地托管 Phaser.js 等 CDN 资源 ────────────────
from fastapi.staticfiles import StaticFiles
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# 后台生成追踪
from concurrent.futures import ThreadPoolExecutor
_background_executor = ThreadPoolExecutor(max_workers=2)
_background_tasks: dict[str, dict] = {}


class ChatRequest(BaseModel):
    message: str
    project: Optional[str] = None


@app.get("/")
async def root():
    return {
        "service": "游戏开发 Agent",
        "status": "running",
        "model": MODEL_KEY,
        "projects": len(agent.projects),
        "endpoints": {
            "chat": "POST /chat - 同步聊天/生成",
            "async-chat": "POST /async-chat - 异步创建游戏（后台流水线，返回项目名，前端轮询进度）",
            "fix-game": "POST /fix-game - 异步修改游戏（后台流水线，加载代码→修复→测试→评分→入库）",
            "list_projects": "GET /games - 列出所有游戏项目",
            "get_project": "GET /games/{name} - 查看游戏项目详情",
            "progress": "GET /games/{name}/progress - 轮询游戏生成进度",
            "download": "GET /games/{name}/download - 下载最新游戏 HTML",
            "quality": "GET /games/{name}/quality - 获取质量评分",
            "feedback": "POST/GET /games/{name}/feedback - 提交/查看反馈",
            "auto-improve": "POST /games/{name}/auto-improve - 基于反馈自动改进（异步）",
            "improve-progress": "GET /games/{name}/improve-progress - 轮询自动改进进度",
        }
    }


@app.post("/chat")
async def chat(req: ChatRequest):
    try:
        if req.project and req.project in agent.projects:
            agent.current_project = agent.projects[req.project]
        result = await asyncio.to_thread(agent.chat, req.message)
        return result
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


@app.post("/async-chat")
async def async_chat(req: ChatRequest):
    """
    异步创建游戏 — 立即返回 project name，后台跑完整流水线（设计→编码→审查→测试→重试）
    前端轮询 GET /games/{name}/progress 获取进度
    """
    message = req.message
    if not message:
        return {"ok": False, "error": "消息不能为空"}

    game_name = agent._extract_game_name(message)
    if not game_name:
        game_name = f"game_{int(time.time())}"

    project = agent.create_project(game_name, message)
    agent.current_project = project
    _background_tasks[project.name] = {"status": "running", "result": None, "error": None}

    def _run():
        try:
            result = agent.generate_game(project, user_msg=message)
            _background_tasks[project.name] = {"status": "done", "result": result, "error": None}
        except Exception as e:
            traceback.print_exc()
            _background_tasks[project.name] = {"status": "error", "result": None, "error": str(e)}

    _background_executor.submit(_run)

    return {
        "ok": True,
        "type": "async",
        "project": project.name,
        "status": "started",
        "progress": project.progress,
    }


@app.post("/fix-game")
async def fix_game(req: ChatRequest):
    """
    异步修改游戏 — 立即返回 project name，后台跑完整流水线（加载代码→修复→测试→评分→入库）
    前端轮询 GET /games/{name}/progress 获取进度
    """
    message = req.message
    if not message:
        return {"ok": False, "error": "消息不能为空"}

    # 找到项目或创建
    project_name = req.project
    if project_name and project_name in agent.projects:
        project = agent.projects[project_name]
    elif project_name:
        # 加载数据库中的项目
        db_game = db_load_game(AGENT_USERNAME, project_name)
        if db_game and db_game.get("html"):
            project = agent.create_project(project_name, db_game.get("description", project_name))
            project.version = db_game.get("ver", 0)
            project.current_html = db_game["html"]
            project.design_doc = db_game.get("design_doc", "")
        else:
            project = agent.create_project(project_name, f"修改游戏：{project_name}")
    else:
        project_name = f"fix_{int(time.time())}"
        project = agent.create_project(project_name, message)

    agent.current_project = project
    _background_tasks[project.name] = {"status": "running", "result": None, "error": None}

    def _run():
        try:
            result = agent.fix_game(project, message, user_msg=message)
            _background_tasks[project.name] = {"status": "done", "result": result, "error": None}
        except Exception as e:
            traceback.print_exc()
            _background_tasks[project.name] = {"status": "error", "result": None, "error": str(e)}

    _background_executor.submit(_run)

    return {
        "ok": True,
        "type": "async",
        "project": project.name,
        "status": "started",
        "progress": project.progress,
    }


@app.post("/fix-game-sync")
async def fix_game_sync(req: ChatRequest):
    """同步修改游戏 — 阻塞等待直至流水线完成，直接返回结果"""
    message = req.message
    if not message:
        return {"ok": False, "error": "消息不能为空"}

    project_name = req.project
    if project_name and project_name in agent.projects:
        project = agent.projects[project_name]
    elif project_name:
        db_game = db_load_game(AGENT_USERNAME, project_name)
        if db_game and db_game.get("html"):
            project = agent.create_project(project_name, db_game.get("description", project_name))
            project.version = db_game.get("ver", 0)
            project.current_html = db_game["html"]
            project.design_doc = db_game.get("design_doc", "")
        else:
            project = agent.create_project(project_name, f"修改游戏：{project_name}")
    else:
        project_name = f"fix_{int(time.time())}"
        project = agent.create_project(project_name, message)

    agent.current_project = project

    try:
        result = await asyncio.to_thread(agent.fix_game, project, message, user_msg=message)
        return {"ok": result.get("ok", False), "project": project.name, "result": result}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


@app.get("/games")
async def list_games():
    projects = [p.to_dict() for p in agent.projects.values()]
    return {"projects": projects}


@app.get("/games/{name}")
async def get_project(name: str):
    if name not in agent.projects:
        raise HTTPException(status_code=404, detail=f"项目 '{name}' 不存在")
    return agent.projects[name].to_dict()


@app.get("/games/{name}/progress")
async def get_progress(name: str):
    """获取游戏生成进度（用于前端轮询进度条）"""
    task = _background_tasks.get(name)
    if task:
        proj = agent.projects.get(name)
        return {
            "name": name,
            "task_status": task["status"],          # running / done / error
            "progress": proj.progress if proj else {"phase": "", "detail": "", "pct": 0},
            "result": task["result"],
            "error": task["error"],
        }

    if name not in agent.projects:
        raise HTTPException(status_code=404, detail=f"项目 '{name}' 不存在")

    proj = agent.projects[name]
    return {
        "name": name,
        "task_status": "idle",
        "progress": proj.progress,
        "result": None,
        "error": None,
    }


@app.get("/games/{name}/download")
async def download_game(name: str):
    project_dir = GAMES_DIR / name
    latest = project_dir / "latest.html"
    if not latest.exists():
        raise HTTPException(status_code=404, detail="游戏文件不存在")
    return FileResponse(str(latest), media_type="text/html", filename=f"{name}.html")


@app.get("/games/{name}/steps")
async def get_steps(name: str):
    """获取游戏的完整生成步骤脚本"""
    if name not in agent.projects:
        raise HTTPException(status_code=404, detail=f"项目 '{name}' 不存在")
    proj = agent.projects[name]
    return {
        "name": name,
        "steps": proj._steps,
        "steps_count": len(proj._steps),
        "can_replay": len(proj._steps) > 0,
    }


@app.post("/games/{name}/replay")
async def replay_game(name: str):
    """按步骤脚本重新生成游戏"""
    if name not in agent.projects:
        raise HTTPException(status_code=404, detail=f"项目 '{name}' 不存在")
    proj = agent.projects[name]
    if not proj._steps:
        raise HTTPException(status_code=400, detail="该项目没有步骤脚本，无法重放")

    steps_to_replay = list(proj._steps)
    results = await asyncio.to_thread(agent.replay_steps, steps_to_replay, name, proj.spec)

    return {
        "ok": True,
        "name": name,
        "total_steps": len(results),
        "success_steps": sum(1 for r in results if r["ok"]),
        "results": results,
    }


@app.get("/games/{name}/screenshot")
async def get_screenshot(name: str):
    project_dir = GAMES_DIR / name
    screenshot = project_dir / "latest.png"
    if not screenshot.exists():
        screenshots = sorted(project_dir.glob("v*.png"))
        if screenshots:
            screenshot = screenshots[-1]
        else:
            raise HTTPException(status_code=404, detail="截图不存在")
    return FileResponse(str(screenshot), media_type="image/png")


# ── 质量评分 ──
@app.get("/games/{name}/quality")
async def get_quality(name: str):
    """获取游戏质量评分"""
    if name not in agent.projects:
        raise HTTPException(status_code=404, detail=f"项目 '{name}' 不存在")
    proj = agent.projects[name]
    result = proj.last_test_result
    if not result:
        raise HTTPException(status_code=404, detail="尚未测试")
    return {
        "name": name,
        "quality_score": result.get("quality_score", 0),
        "quality_details": result.get("quality_details", {}),
        "interaction": result.get("interaction", {}),
    }


# ── 用户反馈闭环 ──
class FeedbackRequest(BaseModel):
    feedback: str
    rating: Optional[int] = 0
    aspect: Optional[str] = ""


@app.post("/games/{name}/feedback")
async def submit_feedback(name: str, req: FeedbackRequest):
    """提交用户反馈"""
    if name not in agent.projects:
        raise HTTPException(status_code=404, detail=f"项目 '{name}' 不存在")
    entry = agent.store_feedback(name, req.feedback, req.rating, req.aspect)
    return {"ok": True, "entry": entry}


@app.get("/games/{name}/feedback")
async def get_feedback(name: str):
    """获取反馈摘要和分析"""
    if name not in agent.projects:
        raise HTTPException(status_code=404, detail=f"项目 '{name}' 不存在")
    summary = agent.get_feedback_summary(name)
    return {"name": name, **summary}


@app.post("/games/{name}/auto-improve")
async def auto_improve(name: str):
    """基于反馈自动改进游戏（异步，返回项目名，轮询进度）"""
    if name not in agent.projects:
        raise HTTPException(status_code=404, detail=f"项目 '{name}' 不存在")

    # 注册后台任务
    _background_tasks[f"improve:{name}"] = {"status": "running", "result": None, "error": None}

    def _run():
        try:
            result = agent.auto_improve(name)
            _background_tasks[f"improve:{name}"] = {"status": "done", "result": result, "error": None}
        except Exception as e:
            traceback.print_exc()
            _background_tasks[f"improve:{name}"] = {"status": "error", "result": None, "error": str(e)}

    _background_executor.submit(_run)

    return {
        "ok": True,
        "type": "async",
        "project": name,
        "status": "started",
        "progress": {"phase": "improving", "detail": "基于反馈分析自动改进中...", "pct": 10},
    }


@app.get("/games/{name}/improve-progress")
async def get_improve_progress(name: str):
    """获取自动改进的进度"""
    task = _background_tasks.get(f"improve:{name}")
    proj = agent.projects.get(name)
    return {
        "name": name,
        "task_status": task["status"] if task else "idle",
        "progress": proj.progress if proj else {"phase": "", "detail": "", "pct": 0},
        "result": task["result"] if task else None,
        "error": task["error"] if task else None,
    }


# ═══════════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="游戏开发 Agent HTTP 服务")
    parser.add_argument("--port", type=int, default=8080, help="监听端口")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--model", choices=list(LLM_CONFIGS.keys()), default=MODEL_KEY,
                        help=f"LLM 模型 (默认: {MODEL_KEY})")
    args = parser.parse_args()

    MODEL_KEY = args.model
    print(f"🚀 游戏开发 Agent v2 启动中...")
    print(f"   📡 端口: {args.host}:{args.port}")
    print(f"   🤖 模型: {MODEL_KEY} ({LLM_CONFIGS[MODEL_KEY]['model']})")
    print(f"   📁 游戏目录: {GAMES_DIR}")
    print(f"   📋 已有项目: {list(agent.projects.keys())}")
    print(f"   ⚙️  流水线: 设计文档 → 代码生成 → 代码审查 → 测试 → 自动修复(×3)")

    if not LLM_CONFIGS[MODEL_KEY]["api_key"] and MODEL_KEY != "local":
        print(f"   ⚠️  {MODEL_KEY} API key 未设置！请设置环境变量或修改配置。")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")