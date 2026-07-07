#!/usr/bin/env python3
"""Chess AI Proxy + Game Hub"""

import http.server
import json
import re
import socket
import sys
import time
import urllib.parse
import urllib.request

PORT = 8656
WWW_ROOT = '/www'
PIKAFISH_HOST = 'pikafish'
PIKAFISH_PORT = 9000
DEEPSEEK_URL = 'https://api.deepseek.com/v1/chat/completions'

MIME = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.png': 'image/png', '.jpg': 'image/jpeg',
    '.svg': 'image/svg+xml', '.ico': 'image/x-icon',
    '.json': 'application/json; charset=utf-8',
    '.txt': 'text/plain; charset=utf-8',
}

OUR_TO_UCI = {
    'r': 'R', 'h': 'N', 'e': 'B', 'a': 'A', 'k': 'K', 'c': 'C', 'p': 'P',
    'R': 'r', 'H': 'n', 'E': 'b', 'A': 'a', 'K': 'k', 'C': 'c', 'P': 'p',
}


class PikafishTCP:
    """Connect to pikafishd over TCP."""

    def __init__(self, host, port):
        self.host = host
        self.port = port

    def _connect(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((self.host, self.port))
        return sock

    def send(self, cmd):
        """Send one UCI command, return all output lines until terminal line."""
        for attempt in range(3):
            try:
                sock = self._connect()
                with sock.makefile('rw', buffering=1) as f:
                    f.write(cmd + '\n')
                    f.flush()
                    lines = []
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        if line == 'END':
                            break
                        if line.startswith('ERROR'):
                            raise RuntimeError(line)
                        lines.append(line)
                    return lines
            except Exception:
                if attempt < 2:
                    time.sleep(1)
                    continue
                raise

    def search(self, fen, depth=10):
        try:
            self.send(f'position fen {fen}')
            lines = self.send(f'go depth {depth}')
            bestmove = [l for l in lines if l.startswith('bestmove')]
            if not bestmove:
                raise RuntimeError('no bestmove')
            m = re.search(r'bestmove\s+(\w+)', bestmove[0])
            if not m or m.group(1) == '(none)':
                raise RuntimeError('no move')
            return m.group(1)
        except Exception:
            self.send('restart')
            self.send(f'position fen {fen}')
            lines = self.send(f'go depth {depth}')
            m = re.search(r'bestmove\s+(\w+)', lines[-1])
            if not m:
                raise RuntimeError('no move after restart')
            return m.group(1)


def board_to_fen(board, color):
    rows = []
    for row in board:
        empty = 0
        fen_row = ''
        for p in row:
            t = (p or {}).get('type', ' ')
            if not t or t == ' ':
                empty += 1
            else:
                if empty:
                    fen_row += str(empty)
                    empty = 0
                fen_row += OUR_TO_UCI.get(t[0], '?')
        if empty:
            fen_row += str(empty)
        rows.append(fen_row)
    side = 'w' if color == 'r' else 'b'
    return f"{'/'.join(rows)} {side} - - 0 1"


class Handler(http.server.SimpleHTTPRequestHandler):

    pikafish: PikafishTCP = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WWW_ROOT, **kwargs)

    def log_message(self, fmt, *args):
        pass

    def do_OPTIONS(self):
        self._cors()
        self.send_response(204)
        self.end_headers()

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')

    def _json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self._cors()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length)) if length > 0 else {}

        if path == '/api/chess-pikafish':
            board = body.get('board', [])
            color = body.get('color', 'r')
            depth = body.get('depth', 10)
            fen = board_to_fen(board, color)

            try:
                uci = Handler.pikafish.search(fen, depth)
            except Exception as e:
                print(f'Pikafish error: {e}', file=sys.stderr, flush=True)
                return self._json(503, {'ok': False, 'error': str(e)})

            fc = ord(uci[0]) - 97
            fr = 9 - int(uci[1])
            tc = ord(uci[2]) - 97
            tr = 9 - int(uci[3])
            return self._json(200, {'ok': True, 'move': {'fr': fr, 'fc': fc, 'tr': tr, 'tc': tc}})

        if path == '/api/chess-ai':
            auth = self.headers.get('Authorization', '')
            api_key = auth[7:] if auth.startswith('Bearer ') else ''
            if not api_key:
                return self._json(400, {'error': 'Missing API key'})
            try:
                req = urllib.request.Request(
                    DEEPSEEK_URL,
                    data=json.dumps(body).encode(),
                    headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
                )
                with urllib.request.urlopen(req, timeout=60) as resp:
                    result = resp.read()
                    self.send_response(resp.status)
                    self._cors()
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Content-Length', len(result))
                    self.end_headers()
                    self.wfile.write(result)
            except Exception as e:
                return self._json(500, {'error': f'Proxy error: {e}'})
            return

        self._json(404, {'error': 'Not found'})


def main():
    print(f'Connecting to pikafish at {PIKAFISH_HOST}:{PIKAFISH_PORT}...', flush=True)
    Handler.pikafish = PikafishTCP(PIKAFISH_HOST, PIKAFISH_PORT)
    Handler.pikafish.send('ping')
    print('Pikafish connected', flush=True)

    server = http.server.HTTPServer(('0.0.0.0', PORT), Handler)
    print(f'Chess AI Proxy + Game Hub running on port {PORT}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
