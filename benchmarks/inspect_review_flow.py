"""Walk the review flow in a real browser and photograph each step.

The browser plugin dispatches clicks but React never sees them, so nothing
that needs a real pointer path can be verified that way. This drives Chrome
over the DevTools Protocol and clicks *from inside the page*, which React does
see, and then reports what is actually on screen at each step.

Usage: ../.venv/bin/python benchmarks/inspect_review_flow.py <port>
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
SHOTS = Path("/tmp/protokol-flow")


def launch() -> None:
    proc = subprocess.Popen(
        [
            CHROME,
            "--headless=new",
            f"--remote-debugging-port={PORT}",
            "--remote-allow-origins=*",
            "--user-data-dir=/tmp/protokol-flow-chrome",
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
        r = self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        if r.get("exceptionDetails"):
            raise RuntimeError(str(r["exceptionDetails"]))
        return r["result"].get("value")

    def shot(self, name: str) -> Path:
        SHOTS.mkdir(parents=True, exist_ok=True)
        out = SHOTS / f"{name}.png"
        data = self.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})
        out.write_bytes(base64.b64decode(data["data"]))
        return out


def click_text(tab: Tab, needle: str) -> bool:
    """Clicks the first button whose visible text contains `needle`."""
    return tab.js(
        """
      ((needle) => {
        const buttons = Array.from(document.querySelectorAll('button, [role=radio]'));
        const target = buttons.find((b) => (b.textContent || '').includes(needle));
        if (!target) return false;
        target.click();
        return true;
      })(%s)
    """
        % json.dumps(needle)
    )


def fill(tab: Tab, label: str, value: str) -> bool:
    """Types into an input the way a person does: focus, then set the value
    through React's own value setter so its onChange actually fires."""
    return tab.js(
        """
      ((label, value) => {
        const input = Array.from(document.querySelectorAll('input'))
          .find((i) => (i.getAttribute('aria-label') || '').includes(label));
        if (!input) return false;
        const setter = Object.getOwnPropertyDescriptor(
          window.HTMLInputElement.prototype, 'value').set;
        input.focus();
        setter.call(input, value);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        return true;
      })(%s, %s)
    """
        % (json.dumps(label), json.dumps(value))
    )


def screen(tab: Tab, title: str) -> None:
    height = tab.js("window.innerHeight")
    total = tab.js("document.documentElement.scrollHeight")
    overflow = tab.js("document.documentElement.scrollWidth > window.innerWidth")
    errors = tab.js(
        """
      Array.from(document.querySelectorAll('p, span, div'))
        .map((e) => e.textContent || '')
        .filter((t) => /Не удалось|undefined|NaN|\\$NaN/.test(t))
        .slice(0, 3).join(' | ')
    """
    )
    print(f"\n--- {title}")
    print(f"    страница: {total}px при окне {height}px → {round(total / height, 1)} экрана")
    print(f"    горизонтальная прокрутка: {'ДА' if overflow else 'нет'}")
    if errors:
        print(f"    !! подозрительный текст: {errors}")
    print(f"    скриншот: {tab.shot(title.replace(' ', '_'))}")


def main() -> int:
    app_port = sys.argv[1] if len(sys.argv) > 1 else "8000"
    launch()
    request = urllib.request.Request(f"http://127.0.0.1:{PORT}/json/new?about:blank", method="PUT")
    with urllib.request.urlopen(request) as response:
        target = json.load(response)["webSocketDebuggerUrl"]
    tab = Tab(target)
    tab.send("Page.enable")
    tab.send("Runtime.enable")
    tab.send("Page.navigate", {"url": f"http://127.0.0.1:{app_port}/"})
    time.sleep(3)

    print("=== 1. документ без выжимки ===")
    if not click_text(tab, ".wav"):
        print("  ВНИМАНИЕ: в истории нет записей")
        return 1
    time.sleep(1.5)
    screen(tab, "document")

    print("\n=== 2. поиск по транскрипту ===")
    filled = fill(tab, "Поиск по расшифровке", "Петров")
    time.sleep(0.8)
    print(f"    поле поиска заполнено: {filled}")
    hits = tab.js("document.querySelectorAll('[data-hit]').length")
    current = tab.js("document.querySelectorAll('.hit-current').length")
    counter = tab.js(
        """
      Array.from(document.querySelectorAll('span'))
        .map((e) => e.textContent || '')
        .find((t) => /^\\d+ из \\d+$|^не найдено$/.test(t.trim())) || '(счётчика нет)'
    """
    )
    print(f"    совпадений подсвечено: {hits}, текущее выделено: {current}")
    print(f"    счётчик: {counter}")
    screen(tab, "search")

    print("\n=== 3. экран проверки перед отправкой ===")
    fill(tab, "Поиск по расшифровке", "")
    time.sleep(0.5)
    opened = click_text(tab, "Составить выжимку")
    time.sleep(2.5)
    print(f"    экран проверки открыт: {opened}")
    print(f"    заголовок: {tab.js('document.querySelector(\"article h2\") ? document.querySelector(\"article h2\").textContent : null')}")
    print(
        "    что уйдёт в модель (первые 160 знаков): "
        + str(tab.js("(() => { const p = Array.from(document.querySelectorAll('section p')).find((x) => (x.textContent||'').includes('PERSON')); return p ? p.textContent.slice(0,160) : null; })()"))
    )
    print(
        "    смета: "
        + str(tab.js("(() => { const p = Array.from(document.querySelectorAll('p')).find((x) => (x.textContent||'').includes('в модель')); return p ? p.textContent : null; })()"))
    )
    print(f"    режимов выжимки: {tab.js('document.querySelectorAll(\"[role=radio]\").length')}")
    print(
        "    кнопки: "
        + str(tab.js("Array.from(document.querySelectorAll('article button')).map((b) => b.textContent.trim()).filter(Boolean)"))
    )
    screen(tab, "review")

    print("\n=== 4. отправляем и проверяем повторную выжимку ===")
    sent = click_text(tab, "Составить выжимку")
    # One provider call; the estimate said a fraction of a cent.
    for _ in range(60):
        time.sleep(1)
        if tab.js("document.body.textContent.includes('Составить заново')"):
            break
    print(f"    отправлено: {sent}")
    print(f"    документ с выжимкой: {tab.js(chr(39).join(['document.body.textContent.includes(', 'Составить заново', ')']))}")
    print(
        "    фактическая стоимость: "
        + str(tab.js("(() => { const p = Array.from(document.querySelectorAll('p')).find((x) => /^\\$[0-9]/.test((x.textContent||'').trim())); return p ? p.textContent : null; })()"))
    )
    screen(tab, "summary")

    print("\n=== 5. панель «составить заново» ===")
    opened = click_text(tab, "Составить заново")
    time.sleep(2.5)
    print(f"    панель открыта: {opened}")
    print(f"    предупреждение о повторной расшифровке: {tab.js(chr(39).join(['!!document.body.textContent.includes(', 'повторно не считается', ')']))}")
    print(
        "    смета в панели: "
        + str(tab.js("(() => { const p = Array.from(document.querySelectorAll('p')).filter((x) => (x.textContent||'').includes('в модель')); return p.length ? p[p.length-1].textContent : null; })()"))
    )
    screen(tab, "resummary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
