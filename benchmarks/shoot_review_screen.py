"""Document the review screen from a real recording, not a seeded session.

The browser plugin dispatches clicks but React never sees them, so the flow is
driven over the DevTools Protocol instead. The audio goes in through a real
file input, exactly as a person's drag-and-drop would arrive -- which means the
masking in the screenshot is the masking that actually happened, not something
typed into the session file by hand.

Usage: ../.venv/bin/python benchmarks/shoot_review_screen.py <port> <audio> [out.png]
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
PORT = 9224


def launch() -> None:
    proc = subprocess.Popen(
        [
            CHROME,
            "--headless=new",
            f"--remote-debugging-port={PORT}",
            "--remote-allow-origins=*",
            "--user-data-dir=/tmp/protokol-shoot-chrome",
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
            return
        except Exception:
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("Chrome не поднялся")


class Tab:
    def __init__(self, url: str) -> None:
        self.ws = websocket.create_connection(url, timeout=60)
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
        r = self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        if r.get("exceptionDetails"):
            raise RuntimeError(str(r["exceptionDetails"]))
        return r["result"].get("value")

    def shot(self, out: Path) -> None:
        out.parent.mkdir(parents=True, exist_ok=True)
        data = self.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})
        out.write_bytes(base64.b64decode(data["data"]))

    def put_file(self, selector: str, path: Path) -> None:
        """Fires a real change event on the file input, as a drop would."""
        root = self.send("DOM.getDocument", {"depth": -1})["root"]["nodeId"]
        node = self.send("DOM.querySelector", {"nodeId": root, "selector": selector})["nodeId"]
        if not node:
            raise RuntimeError(f"не найден {selector}")
        self.send("DOM.setFileInputFiles", {"files": [str(path)], "nodeId": node})


def main() -> int:
    app_port = sys.argv[1] if len(sys.argv) > 1 else "8000"
    audio = Path(sys.argv[2]).resolve()
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("/tmp/protokol-flow/real-review.png")

    launch()
    request = urllib.request.Request(f"http://127.0.0.1:{PORT}/json/new?about:blank", method="PUT")
    with urllib.request.urlopen(request) as response:
        target = json.load(response)["webSocketDebuggerUrl"]
    tab = Tab(target)
    tab.send("Page.enable")
    tab.send("Runtime.enable")
    tab.send("DOM.enable")
    tab.send("Page.navigate", {"url": f"http://127.0.0.1:{app_port}/"})
    time.sleep(3)

    print(f"загружаю {audio.name} через настоящий input…")
    tab.put_file('input[type=file]', audio)

    # Wait for the review screen: it is the only state that has preset radios.
    for _ in range(120):
        time.sleep(1)
        if tab.js("document.querySelectorAll('[role=radio]').length") == 3:
            break
    else:
        print("НЕ ДОШЁЛ до экрана проверки")
        print(tab.js("document.body.textContent.slice(0, 400)"))
        return 1

    print("на экране проверки")
    print("  заголовок :", tab.js("document.querySelector('article h2').textContent"))
    print("  найдено   :", tab.js("(() => { const m = document.body.textContent.match(/(\\d+)\\s+личных данных/); return m ? m[0] : null; })()"))
    print(
        "  уйдёт     : ",
        tab.js("(() => { const p = Array.from(document.querySelectorAll('section p')).find((x) => (x.textContent||'').includes('PERSON')); return p ? p.textContent.slice(0, 120) : null; })()"),
    )
    print("  смета     :", tab.js("(() => { const p = Array.from(document.querySelectorAll('p')).find((x) => (x.textContent||'').includes('в модель')); return p ? p.textContent : null; })()"))
    tab.shot(out)
    print(f"  сохранено : {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())