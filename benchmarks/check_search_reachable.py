"""Does the search survive folding, and does it work while folded?

The search used to live inside the transcript section, so folding the section
folded the search with it -- and a folded transcript has no body to highlight
matches in. This drives a real browser against a real recording: fold the
transcript, type a query, and check both that the field is still there and that
the section opens itself to show what it found.

Usage: python3 benchmarks/check_search_reachable.py <url> [--shot PATH]
"""

from __future__ import annotations

import base64
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
PROFILE = "/tmp/protokol-search-chrome"

WHERE = """
(() => {
  const i = document.querySelector('input[aria-label="Поиск по расшифровке"]');
  if (!i) return 'поля нет';
  const section = i.closest('section');
  if (!section) return 'в шапке документа, вне разделов';
  const h = section.querySelector('h3');
  return 'внутри раздела ' + (h ? h.textContent : '?');
})()
"""

TYPE_INTO_FIELD = """
(() => {
  const i = document.querySelector('input[aria-label="Поиск по расшифровке"]');
  // A missing field is a finding, not a crash: calling a setter with null `this`
  // throws "Illegal invocation", and a check that dies on the bug it was written
  // to catch reports nothing at all.
  if (!i) return false;
  const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  set.call(i, 'протокол');
  i.dispatchEvent(new Event('input', { bubbles: true }));
  return true;
})()
"""

FOLD_TRANSCRIPT = """
(() => {
  const h = Array.from(document.querySelectorAll('section h3'))
    .find((x) => /Расшифровка/.test(x.textContent || ''));
  const b = h && h.querySelector('button');
  if (!b) return false;
  b.click();
  return true;
})()
"""

TRANSCRIPT_OPEN = """
(() => {
  const h = Array.from(document.querySelectorAll('section h3'))
    .find((x) => /Расшифровка/.test(x.textContent || ''));
  const b = h && h.querySelector('button[aria-expanded]');
  return b ? b.getAttribute('aria-expanded') : null;
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
            details = r["exceptionDetails"]
            # "Uncaught" on its own says nothing. The description carries the
            # actual line, and throwing it away turns a one-word fix into a hunt.
            why = (details.get("exception") or {}).get("description") or details.get("text", "")
            raise RuntimeError(why[:300])
        return r["result"].get("value")


def main() -> int:
    url = sys.argv[1]
    shot = sys.argv[2] if len(sys.argv) > 2 else None
    launch()
    tab = Tab(url)
    tab.send("Page.enable")
    tab.send("Runtime.enable")
    tab.send("Page.navigate", {"url": url})
    time.sleep(5)
    tab.js(
        "(() => { const b = Array.from(document.querySelectorAll('li button'))"
        ".find(x => /BMIT|real20/.test(x.textContent || '')); if (b) b.click(); })()"
    )
    for _ in range(20):
        time.sleep(0.5)
        if tab.js("Boolean(document.querySelector('article'))"):
            break

    failures: list[str] = []
    print(f"  поле поиска: {tab.js(WHERE)}")
    if "вне разделов" not in (tab.js(WHERE) or ""):
        failures.append("поле поиска по-прежнему лежит внутри раздела")

    if not tab.js(FOLD_TRANSCRIPT):
        print("ПРОВАЛ: не нашёл раздел «Расшифровка»")
        return 1
    time.sleep(0.8)
    folded_height = tab.js("document.documentElement.scrollHeight")
    print(f"  расшифровка свёрнута, высота {folded_height}px")
    still_there = tab.js("Boolean(document.querySelector('input[aria-label=\"Поиск по расшифровке\"]'))")
    if not still_there:
        print("  поле поиска после сворачивания: НЕТ")

    if still_there:
        tab.js(TYPE_INTO_FIELD)
        time.sleep(1.5)
        opened = tab.js(TRANSCRIPT_OPEN)
        hits = tab.js("document.querySelectorAll('[data-hit]').length")
        print(f"  после запроса: раздел раскрыт = {opened}, подсвечено совпадений = {hits}")
        if opened != "true":
            failures.append("раздел не раскрылся под запрос: совпадения негде показывать")
        if not hits:
            failures.append("подсвеченных совпадений нет — слово нигде не нашлось")

    if shot:
        data = tab.send("Page.captureScreenshot", {"format": "png"})
        Path(shot).write_bytes(base64.b64decode(data["data"]))
        print(f"  снимок: {shot}")

    if failures:
        print("\nПРОВАЛ:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
