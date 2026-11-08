"""Record the demo: animated scenes + a scripted, real run of the app.

Runs Chrome on a virtual X display (Xvfb) and captures it with ffmpeg x11grab,
so nothing touches the real desktop. Generations are real (whatever backend the
running server uses).

    uv run uvicorn socklock_variants.web:create_app --factory --port 8077   # separate shell
    uv run python demo/record.py            # -> demo/raw/*.mp4 + demo/raw/marks.json
    uv run python demo/record.py --only app # just the app flow
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
DISPLAY = ":99"
W, H = 1920, 1080
SCREEN_H = 1500  # extra room for the browser toolbar, cropped out by x11grab
SCALE = 1.4  # CSS px are 1.4 screen px, so the UI reads well at 1080p
APP = os.getenv("DEMO_URL", "http://localhost:8077/")
SCENES = ["1", "2", "3", "4", "12", "13"]
SAMPLE = ROOT / "W44_laundry_confession.txt"

OVERLAY_JS = r"""
(() => {
  const css = `
  #fc { position: fixed; left: 0; top: 0; width: 26px; height: 26px; z-index: 2147483647; pointer-events: none;
        transform: translate(-100px,-100px); transition: none; filter: drop-shadow(0 2px 4px rgba(0,0,0,.5)); }
  #fc svg { width: 26px; height: 26px; }
  .fc-ring { position: fixed; width: 44px; height: 44px; margin: -22px 0 0 -22px; border-radius: 50%; z-index: 2147483646;
        pointer-events: none; border: 3px solid rgba(47,140,255,.9); animation: fcring .55s ease-out forwards; }
  @keyframes fcring { from { transform: scale(.3); opacity: 1 } to { transform: scale(1.4); opacity: 0 } }
  #cap { position: fixed; left: 50%; bottom: 34px; transform: translateX(-50%) translateY(20px); z-index: 2147483645;
        padding: 12px 22px; border-radius: 999px; font: 600 19px -apple-system, "Inter", Roboto, sans-serif; color: #f5f5f7;
        background: rgba(20,22,28,.78); border: 1px solid rgba(255,255,255,.14); backdrop-filter: blur(18px);
        box-shadow: 0 12px 34px rgba(0,0,0,.45); opacity: 0; transition: opacity .45s, transform .45s; pointer-events: none; }
  #cap.on { opacity: 1; transform: translateX(-50%); }
  #cap b { color: #2f8cff; margin-right: 8px; }
  #dragchip { position: fixed; z-index: 2147483640; pointer-events: none; padding: 10px 16px; border-radius: 12px;
        font: 600 15px -apple-system, "Inter", Roboto, sans-serif; color: #f5f5f7; background: rgba(47,140,255,.9);
        box-shadow: 0 14px 30px rgba(0,0,0,.4); transform: translate(18px, 14px); }
  .demo-pulse { outline: 3px solid rgba(255,196,0,.95) !important; outline-offset: 3px; border-radius: 999px;
        animation: dp 1.1s ease-in-out infinite; }
  @keyframes dp { 50% { outline-color: rgba(255,196,0,.25) } }
  #csvview { position: fixed; inset: 60px 80px; z-index: 2147483600; border-radius: 22px; overflow: hidden;
        background: rgb(24,26,32); border: 1px solid rgba(255,255,255,.14); box-shadow: 0 30px 80px rgba(0,0,0,.6);
        font: 14px ui-monospace, Menlo, monospace; color: #f5f5f7; display: flex; flex-direction: column; }
  #csvview header { padding: 16px 22px; font: 600 16px -apple-system, "Inter", Roboto, sans-serif; border-bottom: 1px solid rgba(255,255,255,.1); }
  #csvview .body { overflow: auto; padding: 8px 0; }
  #csvview table { border-collapse: collapse; width: 100%; }
  #csvview td { padding: 7px 18px; border-bottom: 1px solid rgba(255,255,255,.06); white-space: nowrap; max-width: 620px; overflow: hidden; text-overflow: ellipsis; }
  #csvview tr:first-child td { color: #b8b8bf; font-weight: 700; }
  #csvview td:first-child { color: #7fb6ff; }
  `;
  const boot = () => {
    if (document.getElementById("fc")) return;
    const st = document.createElement("style"); st.textContent = css; document.head.append(st);
    const fc = document.createElement("div"); fc.id = "fc";
    fc.innerHTML = '<svg viewBox="0 0 24 24"><path d="M4 2l15 11-6.5 1 3.8 7.2-2.6 1.4-3.8-7.3L4 20z" fill="#fff" stroke="#111" stroke-width="1.3" stroke-linejoin="round"/></svg>';
    document.body.append(fc);
    const cap = document.createElement("div"); cap.id = "cap"; document.body.append(cap);
    addEventListener("mousemove", (e) => {
      fc.style.transform = `translate(${e.clientX - 3}px, ${e.clientY - 2}px)`;
      const d = document.getElementById("dragchip");
      if (d) { d.style.left = e.clientX + "px"; d.style.top = e.clientY + "px"; }
    }, true);
    addEventListener("mousedown", (e) => {
      const r = document.createElement("div"); r.className = "fc-ring";
      r.style.left = e.clientX + "px"; r.style.top = e.clientY + "px";
      document.body.append(r); setTimeout(() => r.remove(), 600);
    }, true);
    window.__cap = (n, text) => {
      const c = document.getElementById("cap");
      if (!text) { c.classList.remove("on"); return; }
      c.innerHTML = `<b>${n}</b>${text}`; c.classList.add("on");
    };
    window.__dragStart = (name) => {
      const d = document.createElement("div"); d.id = "dragchip"; d.textContent = "📄 " + name; document.body.append(d);
      document.getElementById("drop")?.dispatchEvent(new DragEvent("dragenter", { bubbles: true, cancelable: true }));
    };
    window.__dragDrop = (name, text) => {
      document.getElementById("dragchip")?.remove();
      const dt = new DataTransfer(); dt.items.add(new File([text], name, { type: "text/plain" }));
      document.getElementById("drop").dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: dt }));
    };
    window.__pulse = (sel, on) => document.querySelectorAll(sel).forEach((el) => el.classList.toggle("demo-pulse", on));
    window.__csv = async () => {
      const text = await (await fetch("/api/export.csv")).text();
      const rows = text.trim().split(/\r?\n/).slice(0, 16).map((l) => {
        const cells = []; let cur = "", q = false;
        for (const ch of l) { if (ch === '"') q = !q; else if (ch === "," && !q) { cells.push(cur); cur = ""; } else cur += ch; }
        cells.push(cur); return cells.slice(0, 4);
      });
      const v = document.createElement("div"); v.id = "csvview";
      v.innerHTML = `<header>socklock_variants.csv</header><div class="body"><table>${
        rows.map((r) => `<tr>${r.map((c) => `<td></td>`).join("")}</tr>`).join("")}</table></div>`;
      document.body.append(v);
      v.querySelectorAll("tr").forEach((tr, i) => tr.querySelectorAll("td").forEach((td, j) => (td.textContent = rows[i][j])));
    };
  };
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", boot); else boot();
})();
"""


class Capture:
    """ffmpeg x11grab of the whole virtual screen into one mp4."""

    top = 0  # screen px of browser chrome above the page, measured at startup

    def __init__(self, path: Path):
        self.path = path
        self.proc = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-video_size", f"{W}x{H}",
             "-framerate", "30", "-draw_mouse", "0", "-i", f"{DISPLAY}+0,{Capture.top}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p", str(path)],
            stdin=subprocess.PIPE,
        )
        time.sleep(0.6)  # let ffmpeg grab its first frames before t0
        self.t0 = time.monotonic()

    def t(self) -> float:
        return round(time.monotonic() - self.t0, 2)

    def stop(self):
        self.proc.communicate(b"q", timeout=30)


class Cursor:
    def __init__(self, page):
        self.page, self.x, self.y = page, W / SCALE * 0.5, H / SCALE * 0.75

    def to(self, x, y, ms=650):
        steps = max(8, int(ms / 16))
        x0, y0 = self.x, self.y
        for i in range(1, steps + 1):
            k = i / steps
            e = k * k * (3 - 2 * k)
            self.page.mouse.move(x0 + (x - x0) * e, y0 + (y - y0) * e)
            time.sleep(ms / 1000 / steps)
        self.x, self.y = x, y

    def at(self, locator, ms=650, dx=0.5, dy=0.5):
        locator.scroll_into_view_if_needed()
        b = locator.bounding_box()
        self.to(b["x"] + b["width"] * dx, b["y"] + b["height"] * dy, ms)

    def click(self, locator, ms=650):
        self.at(locator, ms)
        time.sleep(0.15)
        self.page.mouse.down(); time.sleep(0.08); self.page.mouse.up()


def pause(s):
    time.sleep(s)


def record_scenes(page, only=None):
    for s in SCENES:
        if only and s not in only:
            continue
        page.goto((ROOT / "scenes.html").as_uri() + f"?s={s}&manual")
        page.wait_for_function("window.__start")
        page.evaluate("document.getElementById('fc')?.remove()")
        cap = Capture(RAW / f"scene{s}.mp4")
        pause(0.4)
        page.evaluate("window.__start()")
        page.wait_for_function("document.body.dataset.done === '1'", timeout=120_000)
        pause(4)  # hold: the edit stretches/trims this to the voice-over
        cap.stop()
        print(f"scene {s} done")


def record_app(page):
    marks = {}
    page.goto(APP)
    page.wait_for_selector("#generate")
    cur = Cursor(page)
    cap = Capture(RAW / "app.mp4")
    mark = lambda k: marks.__setitem__(k, cap.t())  # noqa: E731

    # 5 — script in
    mark("s05")
    pause(1.2)
    page.evaluate("window.__cap('1', 'Перетягни скрипт переможця або встав текст')")
    cur.to(120, H / SCALE - 120, 300)
    page.evaluate(f"window.__dragStart({json.dumps(SAMPLE.name)})")
    cur.at(page.locator("#drop"), 1400, dy=0.45)
    pause(0.4)
    page.evaluate(f"window.__dragDrop({json.dumps(SAMPLE.name)}, {json.dumps(SAMPLE.read_text())})")
    pause(2.5)
    cur.at(page.locator("#script"), 900, dx=0.35, dy=0.3)
    pause(2.5)

    # 6 — count + generate
    mark("s06")
    page.evaluate("window.__cap('2', 'Вибери кількість — за замовчуванням 20 — і генеруй')")
    cur.click(page.locator("#minus"), 900); pause(0.5)
    cur.click(page.locator("#plus"), 400); pause(0.9)
    cur.click(page.locator("#generate"), 800)

    # 7 — wait (sped up in the edit)
    mark("s07")
    page.wait_for_selector("#rows .row", timeout=240_000)
    mark("s07_end")
    pause(1.5)

    # 8 — read the table
    mark("s08")
    page.evaluate("window.__cap('3', 'Кожен варіант: назва для кабінету, що змінено, кут')")
    first = page.locator("#rows .row").first
    cur.at(first.locator(".name"), 900); pause(1.2)
    page.evaluate("window.__pulse('#rows .row:first-child .tag', true)")
    cur.at(first.locator(".tags"), 800, dx=0.2); pause(2.6)
    page.evaluate("window.__pulse('#rows .row:first-child .tag', false)")
    for _ in range(14):
        page.mouse.wheel(0, 90); pause(0.12)
    pause(1.4)
    for _ in range(14):
        page.mouse.wheel(0, -90); pause(0.1)
    pause(1.0)

    # 9 — full view (prefer a variant that adjusted the neighbouring line)
    mark("s09")
    page.evaluate("window.__cap('4', 'Розгорни — повний скрипт: синім нове, жовтим підлаштоване')")
    rows = page.locator("#rows .row")
    target = rows.filter(has_text="змінена сусідня фраза").first
    if not target.count():
        target = rows.nth(0)
    cur.click(target.locator("button.icon").nth(0), 1000)
    pause(1.2)
    target.locator(".full").scroll_into_view_if_needed()
    cur.at(target.locator(".full"), 900, dx=0.4, dy=0.3)
    pause(4.0)

    # 10 — chat fix
    mark("s10")
    page.evaluate("window.__cap('5', 'Щось не так — відкрий чат і напиши, що поправити')")
    cur.click(target.locator("button.icon").nth(1), 900)
    pause(1.4)
    cur.click(page.locator("#msg"), 600)
    page.keyboard.type("коротше і смішніше", delay=85)
    pause(0.6)
    page.keyboard.press("Enter")
    page.wait_for_selector("#msgs .ai.typing", state="detached", timeout=240_000)
    mark("s10_reply")
    pause(4.0)
    cur.click(page.locator("#closeChat"), 900)
    pause(1.2)
    fresh = page.locator("#rows .row.fresh").first
    if fresh.count():
        cur.at(fresh.locator(".name"), 800)
    pause(2.5)

    # 11 — take the result
    mark("s11")
    page.evaluate("window.__cap('6', 'Скопіюй один варіант або вивантаж усі в CSV')")
    row = fresh if fresh.count() else rows.nth(0)
    cur.click(row.locator("button.icon").nth(2), 900)
    pause(1.6)
    # a real download pops Chrome's download bubble over the frame; show the file instead
    page.evaluate("document.getElementById('csv').addEventListener('click', (e) => e.preventDefault())")
    cur.click(page.locator("#csv"), 1000)
    pause(0.8)
    page.evaluate("window.__csv()")
    pause(4.5)
    page.evaluate("window.__cap('', '')")
    pause(0.8)
    mark("end")
    cap.stop()
    (RAW / "marks.json").write_text(json.dumps(marks, indent=2))
    print("app done", marks)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="scene ids and/or 'app'")
    args = ap.parse_args()
    RAW.mkdir(exist_ok=True)

    xvfb = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", f"{W}x{SCREEN_H}x24", "-nolisten", "tcp"])
    time.sleep(1.0)
    os.environ["DISPLAY"] = DISPLAY
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                channel="chrome", headless=False, env={**os.environ, "LANGUAGE": "uk", "LANG": "uk_UA.UTF-8"},
                ignore_default_args=["--enable-automation"],
                args=[f"--window-size={round(W / SCALE)},{round(H / SCALE) + 87}", "--window-position=0,0", "--lang=uk-UA",
                      f"--force-device-scale-factor={SCALE}", "--no-first-run",
                      "--disable-infobars", "--hide-scrollbars", "--disable-features=Translate,TranslateUI,DownloadBubble,DownloadBubbleV2"],
            )
            ctx = browser.new_context(no_viewport=True, color_scheme="dark", accept_downloads=True,
                                      permissions=["clipboard-read", "clipboard-write"])
            ctx.add_init_script(OVERLAY_JS)
            page = ctx.new_page()
            page.goto("about:blank")
            chrome_px = page.evaluate("outerHeight - innerHeight")
            Capture.top = round(chrome_px * SCALE)
            vw, vh = page.evaluate("[innerWidth, innerHeight]")
            print(f"toolbar {Capture.top}px, viewport {vw}x{vh} css px")
            only = set(args.only or [])
            if not only or only - {"app"}:
                record_scenes(page, only - {"app"} or None)
            if not only or "app" in only:
                record_app(page)
            browser.close()
    finally:
        xvfb.terminate()


if __name__ == "__main__":
    sys.exit(main())
