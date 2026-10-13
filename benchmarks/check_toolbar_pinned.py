"""Does the document toolbar actually pin, and does it sit clear of the header?

`sticky` fails quietly: an overflow-hidden ancestor, a `top` larger than the
header, or a margin instead of padding leaves a toolbar that looks correct at
the top of the page and never sticks at all. Nothing about the screenshot says
so, so this scrolls to the middle of the transcript and measures where the
toolbar ended up.

Usage: python3 benchmarks/check_toolbar_pinned.py <url>
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
PROFILE = "/tmp/protokol-toolbar-chrome"

# Toolbar top edge, header bottom edge, and whether the search field is on screen
GEOMETRY = """
(() => {
  const i = document.querySelector('input[aria-label="Поиск по расшифровке"]');
  if (!i) return null;
  const bar = i.closest('div.no-print');
  const head = document.querySelector('header');
  const rgb = (c) => {
    const m = c.match(/\\d+/g);
    return m ? m.slice(0, 3).map(Number).join(',') : c;
  };
  return {
    bar: Math.round(bar.getBoundingClientRect().top),
    barPosition: getComputedStyle(bar).position,
    head: Math.round(head.getBoundingClientRect().bottom),
    fieldVisible: i.getBoundingClientRect().top >= 0 && i.getBoundingClientRect().bottom <= window.innerHeight,
    scrollY: Math.round(window.scrollY),
    // A pinned element is painted in the colour of what it covers. The body is
    // slate-100, and a white bar drew a pale strip across the document.
    barBg: rgb(getComputedStyle(bar).backgroundColor),
    pageBg: rgb(getComputedStyle(document.body).backgroundColor),
  };
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
    tab.send("Page.navigate", {"url": url})
    time.sleep(4)
    tab.js(
        "(() => { const b = Array.from(document.querySelectorAll('li button'))"
        ".find(x => /BMIT|real20/.test(x.textContent || '')); if (b) b.click(); })()"
    )
    for _ in range(20):
        time.sleep(0.4)
        if tab.js("Boolean(document.querySelector('article'))"):
            break

    failures: list[str] = []
    top = tab.js(GEOMETRY)
    if not top:
        print("ПРОВАЛ: панели с поиском нет на документе")
        return 1
    print(f"  наверху страницы: панель на {top['bar']}px, низ шапки {top['head']}px, position={top['barPosition']}")
    if top["barPosition"] != "sticky":
        failures.append(f"панель не sticky, а {top['barPosition']}")
    if top["barBg"] != top["pageBg"]:
        failures.append(f"панель закрашена иначе, чем страница: {top['barBg']} против {top['pageBg']}")

    tab.js("window.scrollTo(0, document.documentElement.scrollHeight / 2)")
    time.sleep(1.0)
    mid = tab.js(GEOMETRY)
    print(f"  прокрутили на {mid['scrollY']}px: панель на {mid['bar']}px, поле видно: {mid['fieldVisible']}")
    if mid["scrollY"] < 500:
        failures.append("страница не прокрутилась — проверка ничего не измеряет")
    if abs(mid["bar"] - mid["head"]) > 2:
        failures.append(f"панель застряла не под шапкой: {mid['bar']}px против {mid['head']}px")
    if not mid["fieldVisible"]:
        failures.append("поле поиска ушло из экрана после прокрутки")

    if failures:
        print("\nПРОВАЛ:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())