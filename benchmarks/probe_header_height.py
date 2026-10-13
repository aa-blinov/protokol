"""Does the app header keep the same height at every width?

A sticky toolbar has to sit exactly below it. A hardcoded offset is only honest
if the number it hardcodes does not move; if it does, the toolbar either floats
over the header or hides behind it, and neither looks like a mistake until
someone scrolls. So measure first, across the widths the audit already uses.

Usage: python3 benchmarks/probe_header_height.py <url>
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cdp import CDP  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9331
PROFILE = "/tmp/protokol-header-chrome"

MEASURE = "Math.round(document.querySelector('header').getBoundingClientRect().height)"
TOOLBAR = """
(() => {
  const i = document.querySelector('input[aria-label="Поиск по расшифровке"]');
  if (!i) return null;
  const row = i.closest('div.no-print');
  return row ? Math.round(row.getBoundingClientRect().height) : null;
})()
"""


def launch() -> None:
    subprocess.Popen(
        [
            CHROME, "--headless=new", f"--remote-debugging-port={PORT}",
            "--remote-allow-origins=*", f"--user-data-dir={PROFILE}",
            "--window-size=1280,900", "--hide-scrollbars", "--no-first-run",
            "--disable-gpu", "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=1) as r:
                if any(p["type"] == "page" for p in json.load(r)):
                    return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("Chrome не поднялся")


class Tab:
    def __init__(self, url: str) -> None:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list") as r:
            page = next(p for p in json.load(r) if p["type"] == "page")
        self.ws = CDP(page["webSocketDebuggerUrl"], timeout=60.0)
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
            raise RuntimeError(str(r["exceptionDetails"])[:200])
        return r["result"].get("value")


def main() -> int:
    url = sys.argv[1]
    launch()
    tab = Tab(url)
    tab.send("Page.enable")
    tab.send("Runtime.enable")

    heights = {}
    for width in (1280, 1024, 900, 640, 420):
        tab.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": width < 700},
        )
        tab.send("Page.navigate", {"url": url})
        time.sleep(3.0)
        tab.js(
            "(() => { const b = Array.from(document.querySelectorAll('li button'))"
            ".find(x => /BMIT|real20/.test(x.textContent || '')); if (b) b.click(); })()"
        )
        for _ in range(20):
            time.sleep(0.4)
            if tab.js("Boolean(document.querySelector('article'))"):
                break
        heights[width] = (tab.js(MEASURE), tab.js(TOOLBAR))
        print(f"  ширина {width:5}px → панель {heights[width][0]}px, панель документа {heights[width][1]}px")

    distinct = {v[0] for v in heights.values()}
    print()
    if len(distinct) == 1:
        print(f"высота постоянна: {distinct.pop()}px — смещение можно задавать числом")
    else:
        print(f"высота меняется: {sorted(distinct)} — нужно измерять в рантайме")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())