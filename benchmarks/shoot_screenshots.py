"""Re-shoot every screenshot in docs/screenshots/ from the current build.

They were captured before the document screen learned to fold, the transcript
search moved into the header, and the settings screen grew a service picker, so
the README was showing an app that no longer exists. Twelve references point at
these files; deleting them was never the option.

Runs against a sidecar with real history, so the document shots show a real
transcription. Writes only into docs/screenshots/.

Usage: python3 benchmarks/shoot_screenshots.py <url>
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
PROFILE = "/tmp/protokol-shots-chrome"
OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"

# name -> (what to do before the shot, window width, full page?)
ALL_SHOTS = [
    ("app-empty", "reset", 1280, False),
    ("app-empty-mobile", "reset", 480, False),
    ("app-results", "document", 1280, False),
    ("app-dark-results", "document-dark", 1280, False),
    ("app-diarization", "transcript", 1280, False),
    ("app-search", "search", 1280, False),
    ("app-history", "rename", 1280, False),
    ("app-settings", "settings", 1280, True),
    ("app-dark-settings", "settings-dark", 1280, True),
]
SHOTS = [row for row in ALL_SHOTS if row[0] in sys.argv[2:]] or ALL_SHOTS

OPEN_DOCUMENT = """
(() => {
  const b = Array.from(document.querySelectorAll('li button'))
    .find((x) => /BMIT/.test(x.textContent || ''));
  if (!b) return false;
  b.click();
  return true;
})()
"""

def THEME(dark: bool) -> str:
    """Set the theme in the running page. Wrapped in parens: a bare arrow
    function concatenated with its call is a syntax error, not an invocation."""
    return (
        "((dark) => { document.documentElement.classList.toggle('dark', dark);"
        " localStorage.setItem('sttshka.theme', dark ? 'dark' : 'light'); })"
        f"({str(dark).lower()})"
    )


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
            why = (details.get("exception") or {}).get("description") or details.get("text", "")
            raise RuntimeError(why[:300])
        return r["result"].get("value")

    def shot(self, name: str, full: bool) -> Path:
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"{name}.png"
        params = {"format": "png"}
        if full:
            params["captureBeyondViewport"] = True
        data = self.send("Page.captureScreenshot", params)
        path.write_bytes(base64.b64decode(data["data"]))
        return path


def set_width(tab: Tab, width: int) -> None:
    tab.send(
        "Emulation.setDeviceMetricsOverride",
        {"width": width, "height": 900, "deviceScaleFactor": 2, "mobile": width < 700},
    )
    time.sleep(0.5)


def apply_theme(tab: Tab, dark: bool) -> None:
    """Set the theme, reload, and check it stuck.

    Two consecutive shots came out byte-identical because the theme leaked from
    the previous one. Nothing said so: both files were written and both looked
    plausible. Reading the class back is the only part that tells the truth.
    """
    tab.js(THEME(dark))
    tab.js("location.reload()")
    time.sleep(2.5)
    for _ in range(12):
        time.sleep(0.4)
        if tab.js("Boolean(document.querySelector('#root'))"):
            break
    tab.js(THEME(dark))
    time.sleep(0.4)
    is_dark = tab.js("document.documentElement.classList.contains('dark')")
    if is_dark != dark:
        raise RuntimeError(f"тема не применилась: ждали {'тёмную' if dark else 'светлую'}")


def open_document(tab: Tab) -> None:
    tab.js("location.reload()")
    time.sleep(2.5)
    for _ in range(20):
        time.sleep(0.5)
        if tab.js("document.querySelectorAll('[data-item]').length"):
            break
    if not tab.js(OPEN_DOCUMENT):
        raise RuntimeError("не открылся документ")
    for _ in range(30):
        time.sleep(0.4)
        if tab.js("Boolean(document.querySelector('section h3'))"):
            return
    raise RuntimeError("документ не дождался разделов")


def main() -> int:
    url = sys.argv[1]
    launch()
    tab = Tab(url)
    tab.send("Page.enable")
    tab.send("Runtime.enable")
    tab.send("Page.navigate", {"url": url})
    time.sleep(4)

    for name, action, width, full in SHOTS:
        set_width(tab, width)
        if action == "reset":
            tab.js("location.reload()")
            time.sleep(2.5)
        elif action.startswith("document"):
            dark = action.endswith("dark")
            apply_theme(tab, dark)
            open_document(tab)
        elif action in ("transcript", "search", "document-top"):
            apply_theme(tab, False)
            open_document(tab)
            tab.js("window.scrollTo(0,0)")
            time.sleep(0.4)
            if action == "transcript":
                tab.js("""(() => { const h = Array.from(document.querySelectorAll('section h3')).find(x => /Расшифровка/.test(x.textContent || '')); if (h) h.scrollIntoView({block:'start'}); })()""")
                time.sleep(0.6)
            if action == "search":
                tab.js("""(() => {
                  const i = document.querySelector('input[aria-label="Поиск по расшифровке"]');
                  const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                  set.call(i, 'протокол');
                  i.dispatchEvent(new Event('input', { bubbles: true }));
                })()""")
                time.sleep(1.2)
                # Park the transcript heading just below the toolbar. Scrolling to
                # the match itself puts the search field off the top, and a shot
                # of a search that does not show the search says nothing.
                tab.js("""(() => { const h = Array.from(document.querySelectorAll('section h3')).find(x => /Расшифровка/.test(x.textContent || '')); if (h) h.scrollIntoView({block:'start'}); })()""")
                time.sleep(0.4)
                tab.js("window.scrollBy(0, -72)")
                time.sleep(0.6)
        elif action in ("settings", "settings-dark"):
            dark = action.endswith("dark")
            apply_theme(tab, dark)
            tab.js("""(() => { const b = Array.from(document.querySelectorAll('button')).find(x => (x.textContent||'').trim() === 'Настройки'); if (b) b.click(); })()""")
            time.sleep(1.5)
        elif action == "rename":
            apply_theme(tab, False)
            tab.js("""(() => { const b = Array.from(document.querySelectorAll('button')).find(x => /^Переименовать запись/.test(x.getAttribute('aria-label') || '')); if (b) b.click(); })()""")
            time.sleep(0.8)

        path = tab.shot(name, full)
        print(f"  {path.name:26} {path.stat().st_size // 1024:4d} КБ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())