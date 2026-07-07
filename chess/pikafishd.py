#!/usr/bin/env python3
"""Pikafish TCP daemon — spawns engine, exposes UCI over TCP."""

import socket
import subprocess
import threading
import time
import sys

PIKAFISH_PATH = '/app/pikafish'
PIKAFISH_NNUE = '/app/pikafish.nnue'
PORT = 9000


class PikafishEngine:
    def __init__(self):
        self.proc = None
        self.lock = threading.Lock()
        self._cond = threading.Condition()
        self._lines = []
        self.ready = False

    def start(self):
        self.proc = subprocess.Popen(
            [PIKAFISH_PATH], cwd='/app',
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )

        def reader():
            for line in iter(self.proc.stdout.readline, ''):
                with self._cond:
                    self._lines.append(line.rstrip())
                    self._cond.notify_all()

        threading.Thread(target=reader, daemon=True).start()

        self._send('uci')
        self._wait_for('uciok', 5000)
        self._send(f'setoption name NNUEFile value {PIKAFISH_NNUE}')
        self._send('isready')
        self._wait_for('readyok', 5000)
        self.ready = True

    def _send(self, line):
        self.proc.stdin.write(line + '\n')
        self.proc.stdin.flush()

    def _wait_for(self, prefix, timeout_ms):
        deadline = time.monotonic() + timeout_ms / 1000
        with self._cond:
            while True:
                for i, line in enumerate(self._lines):
                    if line.startswith(prefix):
                        del self._lines[:i + 1]
                        return line
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f'Timeout waiting for {prefix}')
                self._cond.wait(remaining)

    def command(self, cmd):
        with self.lock:
            # Drain stale lines
            with self._cond:
                self._lines.clear()
            self._send(cmd)
            lines = []
            while True:
                line = self._wait_for('', 60000)
                lines.append(line)
                if line.startswith('bestmove') or line.startswith('uciok') or line.startswith('readyok'):
                    break
                if line.startswith('option name') or line.startswith('id '):
                    if cmd == 'uci':
                        continue
            return '\n'.join(lines)


def handle_client(conn, engine):
    try:
        with conn.makefile('rw', buffering=1) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line == 'restart':
                    print('Restarting pikafish...', flush=True)
                    with engine.lock:
                        engine.proc.kill()
                        engine.proc.wait()
                        engine.ready = False
                        engine._lines.clear()
                        engine.start()
                    conn.sendall(b'ok\n')
                    continue
                if line == 'ping':
                    conn.sendall(b'pong\n')
                    continue
                try:
                    result = engine.command(line)
                    conn.sendall((result + '\n').encode())
                except Exception as e:
                    conn.sendall(f'ERROR {e}\n'.encode())
    finally:
        conn.close()


def main():
    print('Starting Pikafish engine...', flush=True)
    engine = PikafishEngine()
    engine.start()
    print('Pikafish ready', flush=True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', PORT))
    sock.listen(16)
    print(f'Pikafish TCP daemon on port {PORT}', flush=True)

    while True:
        conn, addr = sock.accept()
        threading.Thread(target=handle_client, args=(conn, engine), daemon=True).start()


if __name__ == '__main__':
    main()
