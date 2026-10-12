"""Watch the progress line in a real browser, with the file actually uploaded.

The browser plugin dispatches clicks but React never sees them, so no upload was
possible through it. CDP's DOM.setFileInputFiles can set the file on the hidden
input directly, which fires the same onChange a drag-and-drop would.

Two runs: the first has no timing baseline so no estimate is shown, and that is
correct -- there is nothing to base one on yet. The second has one, and the
progress line shows the remaining time.

Usage: .venv/bin/python benchmarks/watch_progress.py <port> <audio-file>
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
PORT = 9223


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
        r = self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        if r.get("exceptionDetails"):
            raise RuntimeError(str(r["exceptionDetails"]))
        return r["result"].get("value")

    def shot(self, path: Path) -> None:
        r = self.send("Page.captureScreenshot", {"format": "png"})
        path.write_bytes(base64.b64decode(r["data"]))


def main() -> int:
    app_port, audio = sys.argv[1], sys.argv[2]
    subprocess.Popen(
        [CHROME, "--headless=new", f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
         "--user-data-dir=/tmp/protokol-chrome2", "--window-size=1280,900", "--hide-scrollbars",
         "--no-first-run", "--disable-gpu", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1)
            break
        except Exception:
            time.sleep(0.5)

    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/json/new?about:blank", method="PUT")
    tab = Tab(json.load(urllib.request.urlopen(req))["webSocketDebuggerUrl"])
    tab.send("Page.enable")
    tab.send("Runtime.enable")
    tab.send("DOM.enable")
    tab.send("Page.navigate", {"url": f"http://127.0.0.1:{app_port}/"})
    time.sleep(3)

    def upload():
        doc = tab.send("DOM.getDocument")
        node = tab.send(
            "DOM.querySelector", {"nodeId": doc["root"]["nodeId"], "selector": "input[type=file]"}
        )
        tab.send("DOM.setFileInputFiles", {"files": [str(Path(audio).resolve())], "nodeId": node["nodeId"]})

    for run in (1, 2):
        print(f"--- прогон {run}")
        upload()
        time.sleep(4)
        line = tab.js("""
          (() => {
            const el = Array.from(document.querySelectorAll('div')).find(
              (d) => d.className.includes('max-w-md') && d.textContent.includes('%'));
            return el ? el.textContent.replace(/\\s+/g, ' ').trim() : '(строка прогресса не найдена)';
          })()
        """)
        print(f"  строка прогресса: {line}")
        # ждём конца обработки
        for _ in range(240):
            if not tab.js("document.body.textContent.includes('Транскрибация аудио')"):
                break
            time.sleep(1)
        time.sleep(1)

    out = Path("/tmp/progress_line.png")
    tab.shot(out)
    print(f"\nскриншот: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())