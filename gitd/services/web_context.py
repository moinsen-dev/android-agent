"""Web browser context — shared functions used by agent tools and API endpoints.

Manages Playwright browser sessions and exposes the same primitives as
device_context.py so that agent_tools.py can dispatch to either Android or web.

Because Playwright's sync API is bound to the thread that created it, this
module runs Playwright in a single dedicated background thread. All public
functions submit work to that thread and block until the result is ready.
"""

import base64
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright


@dataclass
class WebSession:
    sid: str
    context: BrowserContext
    page: Page
    url: str = ""
    viewport: dict[str, int] | None = None
    created_at: float = 0.0


@dataclass
class _WorkerState:
    """Mutable state that lives only inside the Playwright worker thread."""

    pw: Any = None
    browser: Browser | None = None
    sessions: dict[str, WebSession] = field(default_factory=dict)


class _WorkItem:
    def __init__(self, fn: Callable[[_WorkerState], Any]):
        self.fn = fn
        self.result: Any = None
        self.exception: BaseException | None = None
        self.done = threading.Event()

    def run(self, state: _WorkerState):
        try:
            self.result = self.fn(state)
        except BaseException as e:
            self.exception = e
        finally:
            self.done.set()


class _PlaywrightWorker:
    """Single thread that owns the Playwright browser."""

    def __init__(self):
        self._queue: queue.Queue[_WorkItem] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._queue.put(_WorkItem(lambda _state: None))
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _loop(self):
        """Initialize Playwright and process work items."""
        state = _WorkerState()
        try:
            state.pw = sync_playwright().start()
            state.browser = state.pw.chromium.launch(headless=True)
        except Exception as e:
            import logging

            logging.getLogger(__name__).exception("Failed to start Playwright: %s", e)

        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if self._stop.is_set():
                break
            item.run(state)

        # Cleanup
        for session in list(state.sessions.values()):
            try:
                session.context.close()
            except Exception:
                pass
        state.sessions.clear()
        try:
            if state.browser:
                state.browser.close()
        except Exception:
            pass
        try:
            if state.pw:
                state.pw.stop()
        except Exception:
            pass

    def submit(self, fn: Callable[[_WorkerState], Any]) -> Any:
        """Submit a function to run in the Playwright thread and return its result."""
        self.start()
        item = _WorkItem(fn)
        self._queue.put(item)
        item.done.wait()
        if item.exception is not None:
            raise item.exception
        return item.result


# Global worker instance
_worker = _PlaywrightWorker()


# ── Internal helpers (run inside the worker thread) ───────────────────────────


def _create_session(state: _WorkerState, sid: str | None, viewport: dict[str, int] | None) -> WebSession:
    if state.browser is None:
        raise RuntimeError("Playwright browser is not available")
    sid = sid or f"web-{uuid.uuid4().hex[:8]}"
    context = state.browser.new_context(
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
    state.sessions[sid] = session
    return session


def _get_session(state: _WorkerState, sid: str) -> WebSession | None:
    return state.sessions.get(sid)


def _list_sessions(state: _WorkerState) -> list[dict[str, Any]]:
    return [
        {
            "sid": s.sid,
            "url": s.page.url,
            "viewport": s.viewport,
            "created_at": s.created_at,
        }
        for s in state.sessions.values()
    ]


def _close_session(state: _WorkerState, sid: str) -> bool:
    session = state.sessions.pop(sid, None)
    if not session:
        return False
    try:
        session.context.close()
    except Exception:
        pass
    return True


def _close_all_sessions(state: _WorkerState) -> None:
    for sid in list(state.sessions):
        _close_session(state, sid)


# ── Public API ───────────────────────────────────────────────────────────────


def create_session(sid: str | None = None, viewport: dict[str, int] | None = None) -> WebSession:
    """Create a new browser session. Returns the session object.

    The returned WebSession object contains Playwright handles that must only be
    used inside the worker thread. Public functions below never expose those
    handles to the caller's thread.
    """
    return _worker.submit(lambda state: _create_session(state, sid, viewport))


def get_session(sid: str) -> WebSession | None:
    return _worker.submit(lambda state: _get_session(state, sid))


def list_sessions() -> list[dict[str, Any]]:
    return _worker.submit(_list_sessions)


def close_session(sid: str) -> bool:
    return _worker.submit(lambda state: _close_session(state, sid))


def close_all_sessions() -> None:
    _worker.submit(_close_all_sessions)


# ── Primitives matching device_context.py ─────────────────────────────────────


def screenshot(sid: str, quality: int = 80) -> dict[str, Any]:
    """Take a screenshot of the web page. Returns {image: base64, width, height}."""

    def _fn(state: _WorkerState) -> dict[str, Any]:
        session = _get_session(state, sid)
        if not session:
            raise ValueError(f"Web session not found: {sid}")
        raw = session.page.screenshot(type="jpeg", quality=quality)
        viewport = session.page.viewport_size or {"width": 0, "height": 0}
        return {
            "image": base64.b64encode(raw).decode(),
            "width": viewport["width"],
            "height": viewport["height"],
        }

    return _worker.submit(_fn)


def get_interactive_elements(sid: str) -> list[dict[str, Any]]:
    """Return clickable/focusable elements with idx, text, tag, bounds, center."""

    def _fn(state: _WorkerState) -> list[dict[str, Any]]:
        session = _get_session(state, sid)
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

    return _worker.submit(_fn)


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

    def _fn(state: _WorkerState) -> str:
        session = _get_session(state, sid)
        if not session:
            raise ValueError(f"Web session not found: {sid}")

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

    return _worker.submit(_fn)


def navigate(sid: str, url: str) -> dict[str, Any]:
    """Navigate session to a URL."""

    def _fn(state: _WorkerState) -> dict[str, Any]:
        session = _get_session(state, sid)
        if not session:
            raise ValueError(f"Web session not found: {sid}")
        target = url
        if not target.startswith(("http://", "https://", "data:")):
            target = "https://" + target
        session.page.goto(target, wait_until="domcontentloaded", timeout=30000)
        session.url = session.page.url
        return {"ok": True, "url": session.page.url}

    return _worker.submit(_fn)


def tap(sid: str, x: int, y: int) -> dict[str, Any]:
    """Click at page coordinates."""

    def _fn(state: _WorkerState) -> dict[str, Any]:
        session = _get_session(state, sid)
        if not session:
            raise ValueError(f"Web session not found: {sid}")
        session.page.mouse.click(x, y)
        return {"ok": True, "x": x, "y": y}

    return _worker.submit(_fn)


def tap_element(sid: str, idx: int) -> dict[str, Any]:
    """Click element by index from get_interactive_elements."""

    def _fn(state: _WorkerState) -> dict[str, Any]:
        session = _get_session(state, sid)
        if not session:
            raise ValueError(f"Web session not found: {sid}")
        elements = get_interactive_elements(sid)
        if idx < 0 or idx >= len(elements):
            return {"ok": False, "error": f"Element index {idx} out of range (0-{len(elements) - 1})"}
        el = elements[idx]
        session.page.mouse.click(el["center"]["x"], el["center"]["y"])
        return {"ok": True, "idx": idx}

    return _worker.submit(_fn)


def type_text(sid: str, selector_or_text: str, text: str | None = None) -> dict[str, Any]:
    """Type text into an element.

    Supports two call styles:
      - type_text(sid, text) — type into currently focused element
      - type_text(sid, selector, text) — type into selector (CSS or #idx)
    """

    def _fn(state: _WorkerState) -> dict[str, Any]:
        session = _get_session(state, sid)
        if not session:
            raise ValueError(f"Web session not found: {sid}")

        selector = None
        text_value = text
        if text_value is None:
            text_value = selector_or_text
        else:
            selector = selector_or_text

        if selector is None:
            session.page.keyboard.type(text_value)
        else:
            if selector.startswith("#") and selector[1:].isdigit():
                idx = int(selector[1:])
                elements = get_interactive_elements(sid)
                if idx < 0 or idx >= len(elements):
                    return {"ok": False, "error": f"Element index {idx} out of range"}
                el = elements[idx]
                session.page.mouse.click(el["center"]["x"], el["center"]["y"])
                session.page.keyboard.type(text_value)
            else:
                session.page.fill(selector, text_value)

        return {"ok": True, "text": text_value}

    return _worker.submit(_fn)


def set_viewport(sid: str, width: int, height: int, device_scale_factor: int = 1) -> dict[str, Any]:
    """Resize the browser viewport."""

    def _fn(state: _WorkerState) -> dict[str, Any]:
        session = _get_session(state, sid)
        if not session:
            raise ValueError(f"Web session not found: {sid}")
        session.page.set_viewport_size({"width": width, "height": height})
        session.viewport = {
            "width": width,
            "height": height,
            "device_scale_factor": device_scale_factor,
        }
        return {"ok": True, "viewport": session.viewport}

    return _worker.submit(_fn)


def press_key(sid: str, key: str) -> dict[str, Any]:
    """Press a keyboard key (e.g. Enter, Tab, Escape)."""

    def _fn(state: _WorkerState) -> dict[str, Any]:
        session = _get_session(state, sid)
        if not session:
            raise ValueError(f"Web session not found: {sid}")
        session.page.keyboard.press(key)
        return {"ok": True, "key": key}

    return _worker.submit(_fn)


def scroll(sid: str, x1: int, y1: int, x2: int, y2: int) -> dict[str, Any]:
    """Scroll by dragging from (x1,y1) to (x2,y2)."""

    def _fn(state: _WorkerState) -> dict[str, Any]:
        session = _get_session(state, sid)
        if not session:
            raise ValueError(f"Web session not found: {sid}")
        session.page.mouse.move(x1, y1)
        session.page.mouse.down()
        session.page.mouse.move(x2, y2)
        session.page.mouse.up()
        return {"ok": True}

    return _worker.submit(_fn)


def get_url(sid: str) -> str:
    def _fn(state: _WorkerState) -> str:
        session = _get_session(state, sid)
        if not session:
            raise ValueError(f"Web session not found: {sid}")
        return session.page.url

    return _worker.submit(_fn)


def get_title(sid: str) -> str:
    def _fn(state: _WorkerState) -> str:
        session = _get_session(state, sid)
        if not session:
            raise ValueError(f"Web session not found: {sid}")
        return session.page.title()

    return _worker.submit(_fn)


def evaluate(sid: str, expression: str, arg: Any | None = None) -> Any:
    """Evaluate JavaScript in the page context."""

    def _fn(state: _WorkerState) -> Any:
        session = _get_session(state, sid)
        if not session:
            raise ValueError(f"Web session not found: {sid}")
        return session.page.evaluate(expression, arg)

    return _worker.submit(_fn)
