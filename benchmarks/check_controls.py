"""Do the buttons and input fields look like they came from one place?

Contrast and geometry checks say nothing about this: a control can be perfectly
readable at the right width and still be two pixels shorter than its neighbours.
This walks every screen, reduces each control to the handful of properties a
person actually sees -- height, padding, corner radius, font size, border -- and
prints the groups, so disagreement is visible instead of felt.

Usage: python3 benchmarks/check_controls.py <url>
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
PROFILE = "/tmp/protokol-controls-chrome"

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

# Only what the eye compares between two controls sitting next to each other.
# Colours are left out on purpose: the audit already checks them.
# A field and a button that share a row are read as one control. If their
# heights differ, the eye sees the mismatch before it reads either one — and
# the computed border colour can be identical on both, so a colour check never
# notices. This is the whole reason the search field beside «Скачать .txt» kept
# looking wrong with no other check able to say why.
PAIRS = """
(() => {
  const round = (n) => Math.round(parseFloat(n) || 0);
  const out = [];
  document.querySelectorAll('input:not([type=hidden]), select, textarea').forEach((field) => {
    if (!field.getClientRects().length) return;
    const f = field.getBoundingClientRect();
    // Walk up: the search field's button is two wrappers above it, the key
    // field's is one. Looking only at the immediate parent misses half of them.
    let row = field.parentElement;
    for (let depth = 0; depth < 4 && row; depth++) {
      for (const sibling of row.children) {
        if (sibling === field || sibling.tagName !== 'BUTTON') continue;
        const b = sibling.getBoundingClientRect();
        if (!b.height) continue;
        const beside = b.left >= f.right - 2 || f.left >= b.right - 2;
        const sameRow = Math.min(b.bottom, f.bottom) - Math.max(b.top, f.top) > 0;
        if (beside && sameRow) {
          out.push({
            field: (field.getAttribute('aria-label') || field.placeholder || field.tagName).slice(0, 30),
            fh: round(f.height),
            button: (sibling.getAttribute('aria-label') || sibling.textContent || '').trim().slice(0, 24),
            bh: round(b.height),
          });
        }
      }
      row = row.parentElement;
    }
  });
  return out;
})()
"""

SIGNATURE = """
(() => {
  const round = (n) => Math.round(parseFloat(n) || 0);
  const pick = (el, prop) => getComputedStyle(el)[prop];
  return Array.from(document.querySelectorAll('button, input, select, textarea'))
    .filter((el) => {
      const s = getComputedStyle(el);
      if (s.display === 'none' || s.visibility === 'hidden') return false;
      if (el.type === 'hidden') return false;
      return el.getClientRects().length > 0;
    })
    .map((el) => {
      const s = getComputedStyle(el);
      return {
        tag: el.tagName.toLowerCase(),
        type: el.type || '',
        label: (el.getAttribute('aria-label') || el.textContent || el.value || el.placeholder || '')
          .trim().replace(/\\s+/g, ' ').slice(0, 34),
        height: round(el.getBoundingClientRect().height),
        pad: [round(s.paddingTop), round(s.paddingRight), round(s.paddingBottom), round(s.paddingLeft)].join(' '),
        radius: s.borderTopLeftRadius,
        font: s.fontSize,
        border: `${s.borderTopWidth}/${s.borderTopStyle}`,
      };
    });
})()
"""


def launch() -> None:
    subprocess.Popen(
        [
            CHROME,
            "--headless=new",
            f"--remote-debugging-port={PORT}",
            "--remote-allow-origins=*",
            f"--user-data-dir={PROFILE}",
            "--window-size=1280,900",
            "--hide-scrollbars",
            "--no-first-run",
            "--disable-gpu",
            "about:blank",
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
        result = self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        if result.get("exceptionDetails"):
            raise RuntimeError(result["exceptionDetails"].get("text", "ошибка страницы"))
        return result["result"].get("value")


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else "8000"
    launch()
    tab = Tab(f"http://127.0.0.1:{port}/")
    tab.send("Page.enable")
    tab.send("Runtime.enable")
    # Tab() attaches to whatever page Chrome opened. Without this the first
    # reload runs on about:blank and every screen measures the same two buttons.
    tab.send("Page.navigate", {"url": f"http://127.0.0.1:{port}/"})
    time.sleep(3.0)

    seen: dict[tuple, list[str]] = {}
    fields: list[dict] = []
    pairs: list[dict] = []
    for name, action in SCREENS:
        tab.js("location.reload()")
        time.sleep(2.2)
        for _ in range(15):
            if tab.js("Boolean(document.querySelector('#root'))"):
                break
            time.sleep(0.5)
        if action:
            tab.js(action)
            time.sleep(1.0)
        for item in tab.js(SIGNATURE) or []:
            key = (item["tag"], item["type"], item["height"], item["pad"], item["radius"], item["font"], item["border"])
            seen.setdefault(key, []).append(f"{name}: {item['label']}")
            if item["tag"] in ("input", "select") and item["type"] not in ("hidden", "radio", "checkbox", "file"):
                fields.append(item)
        pairs.extend(tab.js(PAIRS) or [])

    print(f"Групп по внешнему виду: {len(seen)}\n")
    for key, labels in sorted(seen.items(), key=lambda kv: (kv[0][0], kv[0][2])):
        tag, kind, height, pad, radius, font, border = key
        print(f"{tag}{('/' + kind) if kind else ''}  h={height}px  pad={pad}  radius={radius}  font={font}  border={border}")
        print(f"    {len(labels)} шт.: " + "; ".join(labels[:6]) + ("…" if len(labels) > 6 else ""))

    # One verdict, on the thing that actually reads as unfinished: single-line
    # fields of different heights sitting in the same panel. A textarea is
    # excluded on purpose -- several lines tall is what a textarea is for.
    heights = {f["height"] for f in fields}
    radii = {f["radius"] for f in fields}
    if len(heights) > 1:
        print(f"\nПРОВАЛ: однострочные поля разной высоты: {sorted(heights)}")
        for f in fields:
            print(f"    h={f['height']}  {f['tag']}  {f['label']}")
        return 1
    if len(radii) > 1:
        print(f"\nПРОВАЛ: у полей разный угол: {sorted(radii)}")
        return 1
    print(f"\nПоля одного вида: {len(fields)} шт., высота {heights.pop() if heights else '—'}px, угол {radii.pop() if radii else '—'}.")

    mismatched = [p for p in pairs if p["fh"] != p["bh"]]
    for pair in mismatched:
        print(f"  ПРОВАЛ: поле «{pair['field']}» {pair['fh']}px рядом с кнопкой "
              f"«{pair['button']}» {pair['bh']}px")
    if mismatched:
        return 1
    print(f"Поля рядом с кнопками совпадают по высоте: {len(pairs)} шт.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
