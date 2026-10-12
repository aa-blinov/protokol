"""Look at a real result screen in a real browser and measure it.

The browser plugin available in this session dispatches clicks but React never
sees them, so nothing that needs a real pointer path could be verified visually.
This drives Chrome over the DevTools Protocol directly instead.

STALE as of the history move (2026-10-11): it seeded a session into localStorage
and wrote it back under the old `result`-shaped session. History is now held by
the sidecar in a file next to the settings, so seeding here does nothing -- use
`inspect_review_flow.py` (walks the current screens) or `shoot_review_screen.py`
(loads a real recording through a real file input) instead.

Usage: .venv/bin/python benchmarks/measure_result_screen.py <port> [sessions.json]
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import websocket

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9222


def launch() -> str:
    proc = subprocess.Popen(
        [
            CHROME,
            "--headless=new",
            f"--remote-debugging-port={PORT}",
            "--remote-allow-origins=*",
            "--user-data-dir=/tmp/protokol-chrome",
            "--window-size=1280,900",
            "--hide-scrollbars",
            "--no-first-run",
            "--disable-gpu",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1) as r:
                json.load(r)
            return proc.pid and CHROME or CHROME
        except Exception:
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("Chrome не поднялся")


class Tab:
    def __init__(self, url: str) -> None:
        self.ws = websocket.create_connection(url, timeout=30)
        self.n = 0

    def send(self, method: str, params: dict | None = None) -> dict:
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def js(self, expression: str):
        r = self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        if r.get("exceptionDetails"):
            raise RuntimeError(str(r["exceptionDetails"]))
        return r["result"].get("value")

    def shot(self, path: Path, full: bool = True) -> None:
        params = {"format": "png", "captureBeyondViewport": full}
        r = self.send("Page.captureScreenshot", params)
        path.write_bytes(base64.b64decode(r["data"]))


def main() -> int:
    app_port = sys.argv[1] if len(sys.argv) > 1 else "8000"
    sessions = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

    launch()
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/json/new?about:blank", method="PUT")
    with urllib.request.urlopen(req) as r:
        target = json.load(r)["webSocketDebuggerUrl"]
    tab = Tab(target)
    tab.send("Page.enable")
    tab.send("Runtime.enable")

    tab.send("Page.navigate", {"url": f"http://127.0.0.1:{app_port}/"})
    time.sleep(2.5)
    tab.js(f"localStorage.setItem('sttshka.sessions', {json.dumps(json.dumps(sessions))})")
    tab.send("Page.navigate", {"url": f"http://127.0.0.1:{app_port}/"})
    time.sleep(3)

    # `current` starts null on load: the document only appears once a session is
    # picked, so the measurement has to do what a person does and click it.
    clicked = tab.js("""
      (() => {
        const row = document.querySelector('aside ul li button');
        if (!row) return false;
        row.click();
        return true;
      })()
    """)
    time.sleep(1.5)
    print("=== что видит пользователь ===")
    if not clicked:
        print("  ВНИМАНИЕ: в истории нет записей, документ не открылся")
    print("высота окна:       ", tab.js("window.innerHeight"))
    print("высота всей страницы:", tab.js("document.documentElement.scrollHeight"))
    print("экранов прокрутки:  ", round(tab.js("document.documentElement.scrollHeight") / tab.js("window.innerHeight"), 1))
    print("горизонтальная прокрутка:", tab.js("document.documentElement.scrollWidth > window.innerWidth"))
    print()
    print("=== секции на экране ===")
    print(tab.js("""
      Array.from(document.querySelectorAll('section')).map((s) => {
        const label = s.querySelector('h3');
        const top = Math.round(s.getBoundingClientRect().top + window.scrollY);
        const label1 = label ? label.textContent : '(без подписи)';
        return `  ${String(top).padStart(5)} px  ${label1}`;
      }).join('\\n')
    """))
    print()
    print("=== первый экран ===")
    print(tab.js("""
      Array.from(document.querySelectorAll('article h2, article h3, article p'))
        .map((e) => ({ t: e.textContent.trim().slice(0, 52), y: Math.round(e.getBoundingClientRect().top) }))
        .filter((x) => x.y > 0 && x.y < window.innerHeight).map((x) => `  y=${String(x.y).padStart(4)}  ${x.t}`).join('\\n')
    """))

    out = Path("/tmp/result_screen.png")
    tab.shot(out)
    print(f"\nскриншот: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())