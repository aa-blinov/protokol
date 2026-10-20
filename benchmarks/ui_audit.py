"""Contrast audit over the live app, in both themes, across every state.

A clean report here is the only thing that would have caught the dark-theme
preset sitting unreadable at about 1:1. It went unnoticed because the dark
theme is the one most people never switch to, and "the page renders" is not
evidence that the text on it is readable.

Walks three screens, flips the theme between each, reads every text node's own
colour against the nearest painted surface behind it, and applies WCAG 1.4.3:
4.5 for body text, 3 for large (>=24px, or >=18.66px bold).

    .venv/bin/python benchmarks/ui_audit.py <port> [--width 1280]

Exits with the number of failures so verify.sh can gate on it.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdp import CDP  # noqa: E402  (vendored: verify.sh runs system python3)

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CDP_PORT = 9331
PROFILE = "/tmp/protokol-ui-audit"

# Runs inside the page. Returns raw rgb so the maths stays in Python, where it
# can be reasoned about, instead of being spread across a regex.
COLLECT = """(() => {
  // Resolved through a canvas rather than parsed: this project declares
  // colours in oklch, and a regex over rgb() returns null for those, which
  // made every oklch surface look like it had no background at all and sent
  // the audit climbing to a white ancestor. A wrong-but-plausible reading is
  // worse than no reading.
  const ctx = document.createElement('canvas').getContext('2d');
  const parse = (value) => {
    if (!value || value === 'transparent') return { r: 0, g: 0, b: 0, a: 0 };
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = '#000';
    ctx.fillStyle = value;
    ctx.fillRect(0, 0, 1, 1);
    const d = ctx.getImageData(0, 0, 1, 1).data;
    return { r: d[0], g: d[1], b: d[2], a: d[3] / 255 };
  };
  const behind = (el) => {
    let node = el;
    while (node && node !== document.documentElement) {
      const bg = parse(getComputedStyle(node).backgroundColor);
      if (bg && bg.a > 0.95) return bg;
      node = node.parentElement;
    }
    return parse(getComputedStyle(document.body).backgroundColor) || { r: 255, g: 255, b: 255, a: 1 };
  };
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    const text = Array.from(el.childNodes)
      .filter((n) => n.nodeType === 3)
      .map((n) => n.textContent.trim())
      .join('');
    if (!text) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) continue;
    const style = getComputedStyle(el);
    if (style.visibility === 'hidden' || style.opacity === '0') continue;
    out.push({
      tag: el.tagName.toLowerCase(),
      cls: String(el.className || '').slice(0, 70),
      text: text.slice(0, 46),
      fg: parse(style.color),
      bg: behind(el),
      px: Math.round(parseFloat(style.fontSize)),
      weight: style.fontWeight,
    });
  }
  return out;
})()"""

SCREENS = [
    ("пустой экран", ""),
    (
        "документ",
        "Array.from(document.querySelectorAll('[data-item] button'))"
        ".find(b => b.textContent.includes('BMIT'))?.click()",
    ),
    (
        "настройки",
        "Array.from(document.querySelectorAll('button'))"
        ".find(b => b.textContent.trim() === 'Настройки')?.click()",
    ),
]


class Tab:
    def __init__(self, url: str) -> None:
        self.ws = CDP(url, timeout=60)
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
        result = self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        if result.get("exceptionDetails"):
            raise RuntimeError(result["exceptionDetails"].get("text", "ошибка страницы"))
        return result["result"].get("value")


def luminance(colour: dict) -> float:
    def channel(value: float) -> float:
        x = value / 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(colour["r"]) + 0.7152 * channel(colour["g"]) + 0.0722 * channel(colour["b"])


def contrast(ink: dict, surface: dict) -> float:
    a, b = luminance(ink), luminance(surface)
    hi, lo = max(a, b), min(a, b)
    return (round(hi, 2) * 100 + 5) / (round(lo, 2) * 100 + 5)


def required(item: dict) -> float:
    """WCAG 1.4.3: 4.5 for body text, 3 for large — >=24px, or >=18.66px bold."""
    bold = str(item["weight"]).isdigit() and int(item["weight"]) >= 700
    return 3.0 if (item["px"] >= 24 or (item["px"] >= 18.66 and bold)) else 4.5


OVERFLOW = """(() => {
  const doc = document.documentElement;
  const wide = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && (r.right > window.innerWidth + 1 || r.left < -1)) {
      wide.push({ tag: el.tagName.toLowerCase(), cls: String(el.className || '').slice(0, 50),
                  right: Math.round(r.right), left: Math.round(r.left) });
    }
  }
  return { scrollWidth: doc.scrollWidth, innerWidth: window.innerWidth,
           horizontalScroll: doc.scrollWidth > window.innerWidth + 1, offenders: wide.slice(0, 4) };
})()"""


def audit_layout(tab) -> list[str]:
    """Widths, zoom and print. Contrast says nothing about whether a layout
    survives being made narrow, which is where two-column grids break."""
    notes: list[str] = []
    tab.js("location.reload()")
    time.sleep(2.2)
    for _ in range(15):
        if tab.js("document.querySelectorAll('aside li').length") >= 3:
            break
        time.sleep(0.5)

    for width in (1280, 1024, 900, 640):
        tab.send("Emulation.setDeviceMetricsOverride",
                 {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        time.sleep(0.6)
        report = tab.js(OVERFLOW) or {}
        mark = "OK" if not report.get("horizontalScroll") else "ГОРИЗОНТАЛЬНАЯ ПРОКРУТКА"
        notes.append(f"ширина {width}px: {mark}")
        if report.get("offenders"):
            notes.append("    " + "; ".join(f"{o['tag']}.{o['cls'][:26]}" for o in report["offenders"]))

    # 200% zoom is, to the layout, a half-width viewport.
    tab.send("Emulation.setDeviceMetricsOverride",
             {"width": 640, "height": 450, "deviceScaleFactor": 2, "mobile": False})
    time.sleep(0.6)
    zoom = tab.js(OVERFLOW) or {}
    notes.append(
        "зум 200%: " + ("OK" if not zoom.get("horizontalScroll") else "ГОРИЗОНТАЛЬНАЯ ПРОКРУТКА")
    )
    tab.send("Emulation.clearDeviceMetricsOverride")
    time.sleep(0.4)

    # Print is a real medium: measure whether the chrome survives it.
    tab.js(
        "Array.from(document.querySelectorAll('[data-item] button'))"
        ".find(b => b.textContent.includes('BMIT'))?.click()"
    )
    time.sleep(0.9)
    tab.send("Emulation.setEmulatedMedia", {"media": "print"})
    time.sleep(0.5)
    printable = tab.js("document.querySelectorAll('.no-print').length")
    hidden = tab.js(
        "Array.from(document.querySelectorAll('.no-print'))"
        ".filter(el => getComputedStyle(el).display === 'none').length"
    )
    buttons = tab.js("document.querySelectorAll('button').length")
    buttons_left = tab.js(
        "Array.from(document.querySelectorAll('button'))"
        ".filter(b => getComputedStyle(b).display !== 'none').length"
    )
    notes.append(
        f"печать: служебных блоков скрыто {hidden} из {printable}, "
        f"кнопок на бумаге {buttons_left} из {buttons}"
    )
    shot = tab.send("Page.captureScreenshot", {"format": "png"})
    Path("/tmp/ui-print.png").write_bytes(base64.b64decode(shot["data"]))
    tab.send("Emulation.setEmulatedMedia", {"media": "screen"})
    return notes


NESTED = """
(() => {
  const sel = 'button button, button a, a button, a a, button summary, summary button, button input';
  return Array.from(document.querySelectorAll(sel)).map((el) => {
    // The immediate parent is usually a wrapper div; what matters is which
    // interactive element encloses it, so walk up to that one.
    let node = el.parentElement;
    let outer = '?';
    while (node) {
      const tag = node.tagName.toLowerCase();
      if (tag === 'button' || tag === 'a' || tag === 'summary') { outer = tag; break; }
      node = node.parentElement;
    }
    return outer + ' > ' + el.tagName.toLowerCase()
      + ' «' + (el.textContent || el.value || '').trim().slice(0, 28) + '»';
  });
})()
"""


def audit_interactive(tab) -> list[str]:
    """Nested interactive elements, on the document screen.

    A button inside a button is invalid HTML, and in React it also means the
    click meant for the inner control bubbled up and fired the outer handler:
    the section folded itself when the reader asked to copy its text. Neither
    contrast nor geometry catches that, so it is checked here.
    """
    offenders = tab.js(NESTED) or []
    if offenders:
        return ["вложенные интерактивные элементы: " + "; ".join(offenders)]
    return ["вложенных интерактивных элементов нет"]


def main() -> int:
    port = next((a for a in sys.argv[1:] if not a.startswith("--")), "8000")
    width = 1280
    for arg in sys.argv:
        if arg.startswith("--width="):
            width = int(arg.split("=")[1])

    subprocess.Popen(
        [
            CHROME,
            "--headless=new",
            f"--remote-debugging-port={CDP_PORT}",
            "--remote-allow-origins=*",
            f"--user-data-dir={PROFILE}",
            f"--window-size={width},900",
            "--hide-scrollbars",
            "--no-first-run",
            "--disable-gpu",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    target = None
    for _ in range(50):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=1) as response:
                pages = json.load(response)
            target = next((p for p in pages if p["type"] == "page"), None)
            if target:
                break
        except Exception:
            pass
        time.sleep(0.2)
    if not target:
        print("Chrome не поднялся")
        return 2

    tab = Tab(target["webSocketDebuggerUrl"])
    tab.send("Page.enable")
    tab.send("Runtime.enable")
    # Без перехода страница пустая, и первая же evaluate падает на пустом контексте.
    tab.send("Page.navigate", {"url": f"http://127.0.0.1:{port}/"})
    time.sleep(2.5)

    failures: list[dict] = []
    checked = 0

    for screen, action in SCREENS:
        for dark in (False, True):
            tab.js(
                f"document.documentElement.classList.toggle('dark', {str(dark).lower()});"
                f"localStorage.setItem('sttshka.theme', '{'dark' if dark else 'light'}');"
            )
            time.sleep(0.3)
            tab.js(f"location.reload()")
            time.sleep(2.2)
            # Wait for history: without data the screens under test are empty.
            for _ in range(15):
                if tab.js("document.querySelectorAll('aside li').length") >= 3:
                    break
                time.sleep(0.5)
            if action:
                tab.js(action)
                time.sleep(0.8)
            for item in tab.js(COLLECT) or []:
                if not item.get("fg") or not item.get("bg"):
                    continue
                checked += 1
                got = contrast(item["fg"], item["bg"])
                need = required(item)
                if got < need:
                    failures.append({"screen": screen, "theme": "тёмная" if dark else "светлая",
                                     "got": round(got, 2), "need": need, **item})

    layout = audit_layout(tab)
    nested = audit_interactive(tab)
    layout.extend(nested)
    nested_bad = len(nested) and not nested[0].endswith("нет")
    total = len(failures) + (1 if nested_bad else 0)

    Path("/tmp/ui-audit.json").write_text(
        json.dumps({"checked": checked, "failures": failures, "layout": layout,
                    "nested_interactive": nested}, ensure_ascii=False, indent=2))
    print(f"Проверено текстовых пар: {checked}")
    for line in layout:
        print("  " + line)
    print()
    if nested_bad:
        print(f"Провалов: {total}\n")
        print(f"  документ  вложенные интерактивные элементы: {nested[0].split(': ', 1)[-1]}")
        return total
    if not failures:
        print("Контраст в порядке во всех состояниях и обеих темах.")
        return 0

    print(f"Провалов: {total}\n")
    seen = set()
    for failure in failures:
        key = (failure["screen"], failure["theme"], failure["cls"])
        if key in seen:
            continue
        seen.add(key)
        print(f"  {failure['theme']:<8} {failure['screen']:<16} "
              f"{failure['got']:.2f}:1 < {failure['need']}   {failure['px']}px")
        print(f"          <{failure['tag']} class=\"{failure['cls']}\"> {failure['text']}")
        print(f"          текст rgb({failure['fg']['r']},{failure['fg']['g']},{failure['fg']['b']}) "
              f"на rgb({failure['bg']['r']},{failure['bg']['g']},{failure['bg']['b']})")
    return total


if __name__ == "__main__":
    raise SystemExit(main())
