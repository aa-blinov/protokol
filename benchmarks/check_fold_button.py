"""Check that the «Свернуть всё / Развернуть всё» label matches the real state.

The button used to decide what to do from `Object.keys(folded).length === 0`.
Folding a section and unfolding it again leaves its key in the record set to
false, so after one fold/unfold round the header claimed «Развернуть всё» while
everything was already open — and clicking it folded the page instead.

A check that never failed is not a check, so this is run against both the old
bundle and the new one: it must fail on the old and pass on the new.

Usage: python3 benchmarks/check_fold_button.py <url> [shot-prefix]
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
PORT = 9231
SHOTS = Path("/tmp/shots")

# verify.sh runs the sidecar without STTSHKA_ENV_FILE, so its history is empty
# and the document screen has nothing to fold. A check that skips itself is
# worse than no check, so the script seeds one synthetic session of its own and
# puts the history back the way it found it.
SEED = {
    "id": "verify-fold-check",
    "name": "проверка сворачивания.wav",
    "createdAt": "2026-01-01T10:00:00.000Z",
    "analysis": {
        "cache_key": "",
        "transcript": "Спикер 1 [0:00]: Иван Петров открыл встречу и назвал сроки.",
        "masked_text": "Спикер 1 [0:00]: [PERSON_1] открыл встречу и назвал сроки.",
        "entity_map": {"[PERSON_1]": "Иван Петров"},
        "entities": [],
        "segments": [
            {"speaker": 0, "start": 0.0, "end": 3.5, "text": "Иван Петров", "offset": 0},
        ],
        "duration_sec": 3.5,
        "timings": {},
        "cached": True,
    },
    "summary": None,
}

# State of the three document sections, read off the rendered DOM. The trigger
# lives *inside* the heading, so it has to be queried downwards — `closest` looks
# upwards and silently found nothing after the markup was fixed, which made every
# assertion below pass on an empty object.
STATE_JS = """
(() => {
  const out = {};
  document.querySelectorAll('section').forEach((s) => {
    const h = s.querySelector('h3');
    if (!h) return;
    const name = (h.textContent || '').replace(/[^А-Яа-яЁё]/g, '').toLowerCase();
    const trigger = h.querySelector('button[aria-expanded]');
    if (trigger) out[name] = trigger.getAttribute('aria-expanded') === 'true';
  });
  return out;
})()
"""


def launch() -> None:
    proc = subprocess.Popen(
        [
            CHROME,
            "--headless=new",
            f"--remote-debugging-port={PORT}",
            "--remote-allow-origins=*",
            "--user-data-dir=/tmp/protokol-fold-chrome",
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
        # Newer Chrome answers /json/new with 405 unless it is a PUT, and the
        # launch already gave us an about:blank tab, so navigate that one.
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list") as r:
            tabs = json.load(r)
        pages = [t for t in tabs if t.get("type") == "page"]
        if not pages:
            raise RuntimeError("у Chrome нет ни одной вкладки")
        self.ws = CDP(pages[0]["webSocketDebuggerUrl"], timeout=30.0)
        self.n = 0
        self.send("Page.enable")
        self.send("Page.navigate", {"url": url})

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
    """Clicks the first button whose visible text contains `needle`.

    `.click()` from inside the page, because the plugin's synthetic clicks never
    reach React's handlers.
    """
    return tab.js(
        """
      ((needle) => {
        const b = Array.from(document.querySelectorAll('button'))
          .find((x) => (x.textContent || '').includes(needle));
        if (!b) return false;
        b.click();
        return true;
      })(%s)
    """
        % json.dumps(needle)
    )


def header_label(tab: Tab) -> str:
    return tab.js(
        """
      (() => {
        const b = Array.from(document.querySelectorAll('button'))
          .find((x) => /Свернуть всё|Развернуть всё/.test(x.textContent || ''));
        return b ? (b.textContent || '').trim() : 'КНОПКИ НЕТ';
      })()
    """
    )


def api(url: str, path: str, payload=None):
    request = urllib.request.Request(
        url.rstrip("/") + path,
        data=json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method="PUT" if payload is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def main() -> int:
    url = sys.argv[1]
    shot_prefix = sys.argv[2] if len(sys.argv) > 2 else "fold"
    failures: list[str] = []

    history = api(url, "/api/sessions")
    seeded = False
    if not history:
        api(url, "/api/sessions", [SEED])
        seeded = True

    launch()
    tab = Tab(url)
    tab.send("Page.enable")
    tab.send("Runtime.enable")
    time.sleep(4)

    try:
        return run_checks(tab, shot_prefix, failures)
    finally:
        if seeded:
            # Put the history back exactly as it was, including the empty case.
            api(url, "/api/sessions", history)


def run_checks(tab: Tab, shot_prefix: str, failures: list[str]) -> int:
    # Open a recording. The click has to land on the button inside the <li>: the row
    # itself carries no handler, so clicking it dispatches into nothing and the
    # page never changes. Prefers one with a summary, but falls back to any: the
    # seeded session carries none, and the check must still exercise the folding.
    opened = tab.js(
        """
      (() => {
        const rows = Array.from(document.querySelectorAll('li'));
        const row = rows.find((r) => /выжимк/i.test(r.textContent || '')) || rows[0];
        const target = row && row.querySelector('button');
        if (!target) return false;
        target.click();
        return true;
      })()
    """
    )
    if not opened:
        print("ПРОВАЛ: в истории нет ни одной записи")
        return 1

    # The analysis comes back from disk, so wait for the document rather than
    # guessing a sleep long enough to be right on a fast disk and short enough
    # to be wrong on a slow one.
    for _ in range(30):
        time.sleep(0.5)
        # Booleans only: returning the node itself makes CDP walk the DOM and
        # fail with «Object reference chain is too long».
        if tab.js("Boolean(document.querySelector('section h3'))"):
            break
    else:
        print("ПРОВАЛ: документ не открылся")
        return 1

    state = tab.js(STATE_JS)
    # `all({})` is true, so every assertion below would pass on nothing at all.
    # An empty result means the selector no longer matches this markup — that is
    # a broken check, and it must say so instead of reporting OK.
    if len(state) < 3:
        print(f"ПРОВАЛ: нашлось {len(state)} сворачиваемых разделов из трёх — "
              "проверка ничего не проверяет")
        print(f"  что нашлось: {state}")
        return 1

    # Start from a known state: a section that opens folded by default would
    # otherwise keep the header button reading «Развернуть всё» whatever this
    # scenario does to the others.
    if not all(state.values()):
        if click_text(tab, "Развернуть всё"):
            time.sleep(0.7)
            state = tab.js(STATE_JS)
        print(f"  приведено к раскрытому: {state}")

    # The scenario that used to break: fold one section by its header, then
    # open it again. Both clicks are real React state updates.
    tab.js(
        """
      (() => {
        const t = document.querySelector('section button[aria-expanded]');
        if (t) t.click();
      })()
    """
    )
    time.sleep(0.6)
    folded_state = tab.js(STATE_JS)
    tab.js(
        """
      (() => {
        const t = document.querySelector('section button[aria-expanded="false"]');
        if (t) t.click();
      })()
    """
    )
    time.sleep(0.6)

    state = tab.js(STATE_JS)
    label = header_label(tab)

    print(f"  после сворачивания и разворачивания: {folded_state}")
    print(f"  сейчас открыто: {state}")
    print(f"  надпись на кнопке: {label!r}")

    if all(state.values()):
        if label != "Свернуть всё":
            failures.append(
                f"всё открыто, но кнопка пишет {label!r} — кликнет и свернёт"
            )
    else:
        failures.append(f"раздел не вернулся в открытое состояние: {state}")

    # Fold everything, then unfold everything, checking the label each way.
    if not click_text(tab, "Свернуть всё"):
        failures.append("нет кнопки «Свернуть всё»")
    else:
        time.sleep(0.7)
        state = tab.js(STATE_JS)
        label = header_label(tab)
        print(f"  после «Свернуть всё»: {state}, надпись {label!r}")
        if any(state.values()):
            failures.append(f"«Свернуть всё» что-то оставило открытым: {state}")
        if label != "Развернуть всё":
            failures.append(f"после сворачивания надпись {label!r}, ожидалось «Развернуть всё»")
        tab.shot(f"{shot_prefix}-folded")

        click_text(tab, "Развернуть всё")
        time.sleep(0.7)
        state = tab.js(STATE_JS)
        label = header_label(tab)
        print(f"  после «Развернуть всё»: {state}, надпись {label!r}")
        if not all(state.values()):
            failures.append(f"«Развернуть всё» что-то оставило свёрнутым: {state}")
        if label != "Свернуть всё":
            failures.append(f"после разворачивания надпись {label!r}, ожидалось «Свернуть всё»")
        tab.shot(f"{shot_prefix}-open")

    if failures:
        print("\nПРОВАЛ:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
