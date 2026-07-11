"""Web browser context — shared functions used by agent tools and API endpoints.

Manages Playwright browser sessions and exposes the same primitives as
device_context.py so that agent_tools.py can dispatch to either Android or web.
"""

import base64
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

# ── Thread-local Playwright state ────────────────────────────────────────────

_lock = threading.Lock()
_thread_local = threading.local()
_sessions: dict[str, "WebSession"] = {}


@dataclass
class WebSession:
    sid: str
    context: BrowserContext
    page: Page
    url: str = ""
    viewport: dict[str, int] | None = None
    created_at: float = 0.0


def _get_thread_browser() -> Browser:
    """Lazy-start a thread-local headless Chromium browser."""
    if getattr(_thread_local, "browser", None) is not None:
        return _thread_local.browser
    with _lock:
        if getattr(_thread_local, "browser", None) is not None:
            return _thread_local.browser
        _thread_local.pw = sync_playwright().start()
        _thread_local.browser = _thread_local.pw.chromium.launch(headless=True)
        return _thread_local.browser


def create_session(sid: str | None = None, viewport: dict[str, int] | None = None) -> WebSession:
    """Create a new browser session. Returns the session id."""
    browser = _get_thread_browser()
    sid = sid or f"web-{uuid.uuid4().hex[:8]}"
    context = browser.new_context(
        viewport=viewport or {"width": 1280, "height": 720},
        device_scale_factor=viewport.get("device_scale_factor", 1) if viewport else 1,
    )
    page = context.new_page()
    session = WebSession(
        sid=sid,
        context=context,
        page=page,
        viewport=viewport or {"width": 1280, "height": 720},
        created_at=time.time(),
    )
    _sessions[sid] = session
    return session


def get_session(sid: str) -> WebSession | None:
    return _sessions.get(sid)


def list_sessions() -> list[dict[str, Any]]:
    return [
        {
            "sid": s.sid,
            "url": s.page.url,
            "viewport": s.viewport,
            "created_at": s.created_at,
        }
        for s in _sessions.values()
    ]


def close_session(sid: str) -> bool:
    session = _sessions.pop(sid, None)
    if not session:
        return False
    try:
        session.context.close()
    except Exception:
        pass
    return True


def close_all_sessions() -> None:
    for sid in list(_sessions):
        close_session(sid)


# ── Primitives matching device_context.py ─────────────────────────────────────


def screenshot(sid: str, quality: int = 80) -> dict[str, Any]:
    """Take a screenshot of the web page. Returns {image: base64, width, height}."""
    session = get_session(sid)
    if not session:
        raise ValueError(f"Web session not found: {sid}")
    raw = session.page.screenshot(type="jpeg", quality=quality)
    # Determine size from page viewport / screenshot
    viewport = session.page.viewport_size or {"width": 0, "height": 0}
    return {
        "image": base64.b64encode(raw).decode(),
        "width": viewport["width"],
        "height": viewport["height"],
    }


def get_interactive_elements(sid: str) -> list[dict[str, Any]]:
    """Return clickable/focusable elements with idx, text, tag, bounds, center."""
    session = get_session(sid)
    if not session:
        raise ValueError(f"Web session not found: {sid}")

    selectors = [
        "a",
        "button",
        "input",
        "textarea",
        "select",
        '[role="button"]',
        '[role="link"]',
        '[role="textbox"]',
        '[role="searchbox"]',
        '[role="checkbox"]',
        '[role="radio"]',
        '[tabindex]:not([tabindex="-1"])',
    ]
    selector = ", ".join(selectors)

    elements = session.page.query_selector_all(selector)
    result = []
    for idx, el in enumerate(elements):
        try:
            box = el.bounding_box()
            if not box:
                continue
            # Skip hidden/zero-size elements
            if box["width"] <= 0 or box["height"] <= 0:
                continue
            text = (el.inner_text() or "").strip().replace("\n", " ")[:80]
            tag = el.evaluate("e => e.tagName.toLowerCase()")
            el_type = el.get_attribute("type") or ""
            role = el.get_attribute("role") or ""
            aria_label = el.get_attribute("aria-label") or ""
            placeholder = el.get_attribute("placeholder") or ""
            label = text or aria_label or placeholder or el.get_attribute("title") or ""
            result.append(
                {
                    "idx": idx,
                    "text": label,
                    "tag": tag,
                    "type": el_type,
                    "role": role,
                    "bounds": {
                        "x1": int(box["x"]),
                        "y1": int(box["y"]),
                        "x2": int(box["x"] + box["width"]),
                        "y2": int(box["y"] + box["height"]),
                    },
                    "center": {
                        "x": int(box["x"] + box["width"] / 2),
                        "y": int(box["y"] + box["height"] / 2),
                    },
                    "clickable": True,
                }
            )
        except Exception:
            continue
    return result


def _node_info(node: Any) -> str:
    tag = node.get("tagName", "").lower()
    text = (node.get("innerText", "") or "").strip().replace("\n", " ")[:60]
    aria = node.get("ariaLabel", "")
    label = text or aria or ""
    clickable = node.get("isClickable", False)
    flags = []
    if clickable:
        flags.append("clickable")
    flag_str = f" [{','.join(flags)}]" if flags else ""
    label_str = f' "{label}"' if label else ""
    return f"[{tag}]{label_str}{flag_str}"


def get_screen_tree(sid: str, max_nodes: int = 80) -> str:
    """LLM-friendly DOM tree summary."""
    session = get_session(sid)
    if not session:
        raise ValueError(f"Web session not found: {sid}")

    # JS function to walk visible interactive/named nodes
    tree = session.page.evaluate(
        """(maxNodes) => {
            function isVisible(el) {
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            }
            function isUseful(el) {
                const tag = el.tagName.toLowerCase();
                const text = (el.innerText || '').trim();
                const clickable = ['A','BUTTON','INPUT','TEXTAREA','SELECT'].includes(el.tagName) ||
                                  el.getAttribute('role') === 'button' ||
                                  el.getAttribute('role') === 'link' ||
                                  el.onclick !== null ||
                                  el.getAttribute('tabindex') !== null;
                return isVisible(el) && (text.length > 0 || clickable || el.id || el.placeholder || el.getAttribute('aria-label'));
            }
            function getInfo(el, idx) {
                const tag = el.tagName.toLowerCase();
                const text = (el.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 60);
                const role = el.getAttribute('role') || '';
                const aria = el.getAttribute('aria-label') || '';
                const placeholder = el.placeholder || '';
                const label = text || aria || placeholder || el.title || el.id || '';
                const clickable = ['A','BUTTON','INPUT','TEXTAREA','SELECT'].includes(el.tagName) ||
                                  role === 'button' || role === 'link';
                const rect = el.getBoundingClientRect();
                return {
                    idx: idx,
                    tag: tag,
                    label: label,
                    clickable: clickable,
                    bounds: [Math.round(rect.left), Math.round(rect.top), Math.round(rect.right), Math.round(rect.bottom)]
                };
            }
            function walk(el, depth, out, counter) {
                if (out.length >= maxNodes) return counter;
                if (isUseful(el)) {
                    const info = getInfo(el, counter.value);
                    counter.value++;
                    out.push({depth: depth, ...info});
                }
                for (const child of el.children) {
                    counter = walk(child, depth + 1, out, counter);
                }
                return counter;
            }
            const out = [];
            walk(document.body, 0, out, {value: 1});
            return out;
        }""",
        max_nodes,
    )

    lines = []
    for node in tree:
        indent = "  " * min(node["depth"], 6)
        flags = []
        if node.get("clickable"):
            flags.append("clickable")
        flag_str = f" [{','.join(flags)}]" if flags else ""
        label_str = f' "{node["label"]}"' if node.get("label") else ""
        bounds = node.get("bounds", [0, 0, 0, 0])
        lines.append(f"{indent}[{node['idx']}] {node['tag']}{label_str}{flag_str} [{bounds[0]},{bounds[1]}][{bounds[2]},{bounds[3]}]")

    if not lines:
        return "(empty page)"
    return "\n".join(lines)


def navigate(sid: str, url: str) -> dict[str, Any]:
    """Navigate session to a URL."""
    session = get_session(sid)
    if not session:
        raise ValueError(f"Web session not found: {sid}")
    if not url.startswith(("http://", "https://", "data:")):
        url = "https://" + url
    session.page.goto(url, wait_until="domcontentloaded", timeout=30000)
    session.url = session.page.url
    return {"ok": True, "url": session.page.url}


def tap(sid: str, x: int, y: int) -> dict[str, Any]:
    """Click at page coordinates."""
    session = get_session(sid)
    if not session:
        raise ValueError(f"Web session not found: {sid}")
    session.page.mouse.click(x, y)
    return {"ok": True, "x": x, "y": y}


def tap_element(sid: str, idx: int) -> dict[str, Any]:
    """Click element by index from get_interactive_elements."""
    elements = get_interactive_elements(sid)
    if idx < 0 or idx >= len(elements):
        return {"ok": False, "error": f"Element index {idx} out of range (0-{len(elements) - 1})"}
    el = elements[idx]
    return tap(sid, el["center"]["x"], el["center"]["y"])


def type_text(sid: str, selector_or_text: str, text: str | None = None) -> dict[str, Any]:
    """Type text into an element.

    Supports two call styles:
      - type_text(sid, text) — type into currently focused element
      - type_text(sid, selector, text) — type into selector (CSS or #idx)
    """
    session = get_session(sid)
    if not session:
        raise ValueError(f"Web session not found: {sid}")

    # Determine selector and text
    selector = None
    if text is None:
        text = selector_or_text
    else:
        selector = selector_or_text

    if selector is None:
        # Focus currently active element and type
        session.page.keyboard.type(text)
    else:
        if selector.startswith("#") and selector[1:].isdigit():
            idx = int(selector[1:])
            elements = get_interactive_elements(sid)
            if idx < 0 or idx >= len(elements):
                return {"ok": False, "error": f"Element index {idx} out of range"}
            el = elements[idx]
            session.page.mouse.click(el["center"]["x"], el["center"]["y"])
            session.page.keyboard.type(text)
        else:
            session.page.fill(selector, text)

    return {"ok": True, "text": text}


def set_viewport(sid: str, width: int, height: int, device_scale_factor: int = 1) -> dict[str, Any]:
    """Resize the browser viewport."""
    session = get_session(sid)
    if not session:
        raise ValueError(f"Web session not found: {sid}")
    session.page.set_viewport_size({"width": width, "height": height})
    session.viewport = {
        "width": width,
        "height": height,
        "device_scale_factor": device_scale_factor,
    }
    return {"ok": True, "viewport": session.viewport}


def press_key(sid: str, key: str) -> dict[str, Any]:
    """Press a keyboard key (e.g. Enter, Tab, Escape)."""
    session = get_session(sid)
    if not session:
        raise ValueError(f"Web session not found: {sid}")
    session.page.keyboard.press(key)
    return {"ok": True, "key": key}


def scroll(sid: str, x1: int, y1: int, x2: int, y2: int) -> dict[str, Any]:
    """Scroll by dragging from (x1,y1) to (x2,y2)."""
    session = get_session(sid)
    if not session:
        raise ValueError(f"Web session not found: {sid}")
    session.page.mouse.move(x1, y1)
    session.page.mouse.down()
    session.page.mouse.move(x2, y2)
    session.page.mouse.up()
    return {"ok": True}


def get_url(sid: str) -> str:
    session = get_session(sid)
    if not session:
        raise ValueError(f"Web session not found: {sid}")
    return session.page.url


def get_title(sid: str) -> str:
    session = get_session(sid)
    if not session:
        raise ValueError(f"Web session not found: {sid}")
    return session.page.title()
