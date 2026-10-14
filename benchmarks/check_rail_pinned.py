"""Does the history rail stay in view while a long document scrolls?

On wide screens the rail is the left column of the app. It is sticky under the header, so the
history and its search field stay reachable while a document scrolls. Below the lg breakpoint the
rail sits under the document and is not pinned.

The working area is lengthened in the page only: an empty spacer is appended to <main>. Nothing is
written anywhere, so the user's history is untouched. The rail is then measured at the top of the
page, in the middle, and at a narrow width.

Usage: python3 benchmarks/check_rail_pinned.py <url>
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
PORT = 9351
PROFILE = "/tmp/protokol-rail-chrome"
# The rail's top is the header's bottom plus 1.5rem (24 px), see the .rail rule in index.css.
GAP_PX = 24

SPACER_JS = """
(() => {
  const main = document.querySelector('main');
  if (!main) return false;
  if (!document.getElementById('rail-check-spacer')) {
    const spacer = document.createElement('div');
    spacer.id = 'rail-check-spacer';
    spacer.setAttribute('aria-hidden', 'true');
    spacer.style.height = '2400px';
    main.appendChild(spacer);
  }
  return true;
})()
"""

GEOMETRY = """
(() => {
  const rail = document.querySelector('aside.rail');
  const head = document.querySelector('header');
  if (!rail || !head) return null;
  const box = rail.getBoundingClientRect();
  const style = getComputedStyle(rail);
  return {
    rail: Math.round(box.top),
    railBottom: Math.round(box.bottom),
    head: Math.round(head.getBoundingClientRect().bottom),
    position: style.position,
    overflowY: style.overflowY,
    inner: window.innerHeight,
    scrollY: Math.round(window.scrollY),
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


def set_width(tab: Tab, width: int) -> None:
    tab.send(
        "Emulation.setDeviceMetricsOverride",
        {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": False},
    )


def main() -> int:
    url = sys.argv[1]
    launch()
    tab = Tab(url)
    tab.send("Page.enable")
    tab.send("Runtime.enable")
    set_width(tab, 1280)
    tab.send("Page.navigate", {"url": url})
    time.sleep(4)
    for _ in range(20):
        if tab.js("Boolean(document.querySelector('aside.rail') && document.querySelector('header'))"):
            break
        time.sleep(0.4)

    if not tab.js(SPACER_JS):
        print("ПРОВАЛ: нет рабочей области <main>")
        return 1
    time.sleep(0.5)

    failures: list[str] = []
    top = tab.js(GEOMETRY)
    if not top:
        print("ПРОВАЛ: нет панели истории (aside.rail)")
        return 1
    print(f"  наверху: панель на {top['rail']}px, низ шапки {top['head']}px, position={top['position']}")
    if top["position"] != "sticky":
        failures.append(f"на широком экране панель не sticky, а {top['position']}")
    if top["rail"] < top["head"]:
        failures.append("панель в начале страницы уходит под шапку")

    tab.js("window.scrollTo(0, 800)")
    time.sleep(1.0)
    mid = tab.js(GEOMETRY)
    print(
        f"  прокрутили на {mid['scrollY']}px: панель на {mid['rail']}px, "
        f"низ панели {mid['railBottom']}px при высоте окна {mid['inner']}px"
    )
    if mid["scrollY"] < 500:
        failures.append("страница не прокрутилась — проверка ничего не измеряет")
    if abs(mid["rail"] - (mid["head"] + GAP_PX)) > 2:
        failures.append(
            f"панель застряла не под шапкой: {mid['rail']}px против {mid['head'] + GAP_PX}px"
        )
    if mid["railBottom"] > mid["inner"] + 1:
        failures.append(
            f"панель выходит за низ окна: {mid['railBottom']}px при высоте {mid['inner']}px"
        )
    if mid["overflowY"] != "auto":
        failures.append(f"панель не прокручивается сама: overflow-y={mid['overflowY']}")

    set_width(tab, 800)
    time.sleep(0.8)
    narrow = tab.js(GEOMETRY)
    tab.send("Emulation.clearDeviceMetricsOverride", {})
    if narrow:
        print(f"  узкий экран (800px): position={narrow['position']}")
        if narrow["position"] == "sticky":
            failures.append("на узком экране панель закреплена и закрывает документ")

    if failures:
        for failure in failures:
            print(f"  ПРОВАЛ: {failure}")
        return 1
    print("  панель истории закреплена при прокрутке, на узком экране не закрепляется")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
