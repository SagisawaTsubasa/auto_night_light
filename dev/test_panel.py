#!/usr/bin/env python3
"""Playwright smoke for the auto_night_light page (L2) + screenshots (L3)."""

from __future__ import annotations

import importlib.util
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SHOTS = Path(__file__).resolve().parent / "shots"
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(
        ("  ok  " if cond else "FAIL  ")
        + name
        + (f": {detail}" if detail and not cond else "")
    )
    if not cond:
        FAILURES.append(f"{name}: {detail}")


def start_server() -> tuple[ThreadingHTTPServer, int]:
    spec = importlib.util.spec_from_file_location(
        "anl_serve", Path(__file__).parent / "serve.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    server = ThreadingHTTPServer(("127.0.0.1", 0), mod.DevHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def main() -> int:
    from playwright.sync_api import sync_playwright

    server, port = start_server()
    base = f"http://127.0.0.1:{port}"
    SHOTS.mkdir(exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            run_checks(browser, base)
        finally:
            browser.close()
    server.shutdown()

    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s)")
        return 1
    print("\nall green")
    return 0


def wait_page_dom(page, selector: str, label: str, timeout_ms: int = 9000) -> None:
    page.wait_for_function(
        """(sel) => {
          const p = document.getElementById('hub');
          if (!p || !p.shadowRoot) return false;
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            if (el.shadowRoot && el.shadowRoot.querySelector(sel)) return true;
          }
          return false;
        }""",
        arg=selector,
        timeout=timeout_ms,
    )
    check(label, True)


def card_text(page, selector: str) -> str:
    return page.evaluate(
        """(sel) => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            const card = el.shadowRoot && el.shadowRoot.querySelector(sel);
            if (card) return card.textContent;
          }
          return '';
        }""",
        selector,
    )


def run_checks(browser, base: str) -> None:
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(base + "/")
    wait_page_dom(page, '[data-manager="m1"]', "page mounts: manager card renders")
    wait_page_dom(page, '[data-light="light.bedroom"]', "light cards render")

    tabs = page.evaluate(
        """() => [...document.getElementById('hub').shadowRoot.querySelectorAll('.fx-tab')]
                 .map(t => ({badge: t.querySelector('.fx-badge').textContent, sel: t.getAttribute('aria-selected')}))"""
    )
    check(
        "anl tab present and selected",
        len(tabs) == 1 and tabs[0]["badge"] == "anl" and tabs[0]["sel"] == "true",
        str(tabs),
    )

    text = card_text(page, '[data-manager="m1"]')
    # ANL-F-022: the three render faces below used to compensate for each
    # other ("06:30" also matched a table row, "日间" also matched a summary
    # tag) — assert each within its own DOM scope.
    chip_text = card_text(page, '[data-manager="m1"] .cx-status')
    expected_anchor = page.evaluate(
        """() => {
          const d = new Date('2026-10-13T06:30:00+08:00');
          return d.toLocaleString('zh-Hans', { hour12: false });
        }"""
    )
    check(
        "global chips: current mode + next anchor",
        "当前：夜间" in chip_text and ("下次锚点 " + expected_anchor) in chip_text,
        chip_text[:160] + " / expect=" + expected_anchor,
    )
    rows = page.evaluate(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            const card = el.shadowRoot && el.shadowRoot.querySelector('[data-manager="m1"]');
            if (card) {
              return [...card.querySelectorAll('tbody tr')].map(
                (tr) => tr.textContent.trim()
              );
            }
          }
          return [];
        }"""
    )
    check("anchor table rows", any("夜间" in r for r in rows) and any("日间" in r for r in rows), str(rows))
    # ANL-F-016: 新渲染面断言——配置摘要行、按钮作用域文案、额外时段 1 基
    check("config summary tags render",
          all(t in text for t in ("入夜", "天亮", "尊重手动", "日间时段")), "")
    check("trigger button states full-entry scope", "立即触发（全部条目）" in text, "")
    check("extra anchor label is 1-based", "额外时段 1" in text, "")

    check(
        "verified light shows target/applied",
        "已验证" in text
        and "目标 12% / 2700K" in text
        and "已下发 12% / 2700K" in text,
        "",
    )
    hallway = card_text(page, '[data-light="light.hallway"]')
    check(
        "mismatch light shows override + steps",
        "偏离" in hallway and "手动接管" in hallway and "连续偏离 2 步" in hallway,
        hallway[:100],
    )
    attic = card_text(page, '[data-light="light.attic"]')
    check(
        "offline light shows error",
        "实体离线" in attic and "灯实体不可用" in attic,
        attic[:100],
    )

    # trigger -> service call + ack toast
    page.evaluate(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            const btn = el.shadowRoot && el.shadowRoot.querySelector('[data-action="trigger"]');
            if (btn) { btn.click(); return true; }
          }
          return false;
        }"""
    )
    page.wait_for_function(
        """() => (window.__serviceCalls || []).some(c => c.domain === 'auto_night_light' && c.service === 'trigger_now')""",
        timeout=4000,
    )
    check("trigger calls trigger_now", True)
    page.wait_for_function(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            if (el.shadowRoot && el.shadowRoot.querySelector('.fx-toast')) return true;
          }
          return false;
        }""",
        timeout=4000,
    )
    check("ack toast appears", True)

    # failapi -> error card
    page2 = browser.new_page(viewport={"width": 1280, "height": 900})
    page2.goto(base + "/?failapi=1")
    page2.wait_for_function(
        """() => {
          const p = document.getElementById('hub');
          for (const el of p.shadowRoot.querySelectorAll('*')) {
            if (el.shadowRoot && el.shadowRoot.querySelector('.fx-error')) return true;
          }
          return false;
        }""",
        timeout=9000,
    )
    check("failapi renders error card", True)
    page2.close()

    # badmodule -> shell error card
    page3 = browser.new_page(viewport={"width": 1280, "height": 900})
    page3.goto(base + "/?badmodule=1")
    page3.wait_for_timeout(900)
    card = page3.evaluate(
        """() => {
          const c = document.getElementById('hub').shadowRoot.querySelector('.fx-error');
          return c ? !!c.querySelector('button') : false;
        }"""
    )
    check("bad module shows shell error card with retry", card is True, str(card))
    page3.close()

    # standalone fallback
    page4 = browser.new_page(viewport={"width": 1280, "height": 900})
    page4.goto(base + "/?standalone=1")
    page4.wait_for_function(
        """() => {
          const el = document.getElementById('page');
          return el && el.shadowRoot && el.shadowRoot.querySelector('[data-manager="m1"]') !== null;
        }""",
        timeout=9000,
    )
    check("standalone fallback boots from vendored kit/tokens", True)
    page4.close()

    check("no page errors so far", not errors, "; ".join(errors[:3]))

    shots = [
        ("/", "p2-light-desktop.png", 1280, 900),
        ("/?dark=1", "p2-dark-desktop.png", 1280, 900),
        ("/", "p2-light-narrow.png", 390, 844),
        ("/?dark=1", "p2-dark-narrow.png", 390, 844),
    ]
    for path, name, w, h in shots:
        sp = browser.new_page(viewport={"width": w, "height": h})
        sp.goto(base + path)
        sp.wait_for_timeout(900)
        sp.screenshot(path=str(SHOTS / name), full_page=False)
        sp.close()
        check(f"shot {name}", (SHOTS / name).is_file())

    page.close()


if __name__ == "__main__":
    raise SystemExit(main())
