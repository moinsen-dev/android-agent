"""Web browser routes: create sessions, navigate, click, type, screenshot, viewport."""

from fastapi import APIRouter, Body, HTTPException

from gitd.services import web_context

router = APIRouter(prefix="/api/web", tags=["web"])


@router.post("/session", summary="Create Web Browser Session")
def web_create_session(data: dict = Body({})):
    """Create a new headless browser session with optional viewport."""
    viewport = data.get("viewport")
    session = web_context.create_session(viewport=viewport)
    return {
        "ok": True,
        "sid": session.sid,
        "url": session.page.url,
        "viewport": session.viewport,
    }


@router.get("/sessions", summary="List Web Sessions")
def web_list_sessions():
    """List active web browser sessions."""
    return {"sessions": web_context.list_sessions()}


@router.delete("/session/{sid}", summary="Close Web Session")
def web_close_session(sid: str):
    """Close a browser session and free resources."""
    ok = web_context.close_session(sid)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


@router.post("/navigate", summary="Navigate To URL")
def web_navigate(data: dict = Body({})):
    """Navigate a web session to a URL."""
    sid = data.get("sid", "")
    url = data.get("url", "")
    if not sid or not url:
        raise HTTPException(status_code=400, detail="sid and url required")
    try:
        result = web_context.navigate(sid, url)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/screenshot/{sid}", summary="Take Web Screenshot")
def web_screenshot(sid: str):
    """Take a screenshot of the web page. Returns base64 JPEG."""
    try:
        result = web_context.screenshot(sid)
        return {"ok": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/elements/{sid}", summary="Get Web Interactive Elements")
def web_elements(sid: str):
    """Get interactive DOM elements (links, buttons, inputs) with bounds."""
    try:
        elements = web_context.get_interactive_elements(sid)
        return {"ok": True, "elements": elements, "count": len(elements)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/screen-tree/{sid}", summary="Get Web Screen Tree")
def web_screen_tree(sid: str):
    """Get LLM-readable DOM tree summary."""
    try:
        tree = web_context.get_screen_tree(sid)
        return {"ok": True, "tree": tree}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tap", summary="Tap/Click On Web Page")
def web_tap(data: dict = Body({})):
    """Click at coordinates (x, y) on the web page."""
    sid = data.get("sid", "")
    if not sid:
        raise HTTPException(status_code=400, detail="sid required")
    try:
        if "idx" in data:
            result = web_context.tap_element(sid, int(data["idx"]))
        else:
            result = web_context.tap(sid, int(data.get("x", 0)), int(data.get("y", 0)))
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/type", summary="Type Text On Web Page")
def web_type(data: dict = Body({})):
    """Type text into focused element or selector."""
    sid = data.get("sid", "")
    text = data.get("text", "")
    selector = data.get("selector")
    if not sid or not text:
        raise HTTPException(status_code=400, detail="sid and text required")
    try:
        result = web_context.type_text(sid, selector or text, text if selector else None)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/viewport", summary="Set Web Viewport Size")
def web_viewport(data: dict = Body({})):
    """Resize the browser viewport."""
    sid = data.get("sid", "")
    width = int(data.get("width", 1280))
    height = int(data.get("height", 720))
    dsf = int(data.get("device_scale_factor", 1))
    if not sid:
        raise HTTPException(status_code=400, detail="sid required")
    try:
        result = web_context.set_viewport(sid, width, height, dsf)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/key", summary="Press Key On Web Page")
def web_key(data: dict = Body({})):
    """Press a keyboard key (Enter, Tab, Escape, etc.)."""
    sid = data.get("sid", "")
    key = data.get("key", "")
    if not sid or not key:
        raise HTTPException(status_code=400, detail="sid and key required")
    try:
        result = web_context.press_key(sid, key)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scroll", summary="Scroll Web Page")
def web_scroll(data: dict = Body({})):
    """Scroll the web page. Accepts either deltas (dx, dy) or drag coordinates (x1,y1,x2,y2)."""
    sid = data.get("sid", "")
    if not sid:
        raise HTTPException(status_code=400, detail="sid required")
    try:
        if "dx" in data or "dy" in data:
            result = web_context.scroll_wheel(sid, int(data.get("dx", 0)), int(data.get("dy", 0)))
        else:
            result = web_context.scroll(
                sid,
                int(data.get("x1", 0)),
                int(data.get("y1", 0)),
                int(data.get("x2", 0)),
                int(data.get("y2", 0)),
            )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/url/{sid}", summary="Get Current URL")
def web_url(sid: str):
    """Return the current URL of a web session."""
    try:
        return {"ok": True, "url": web_context.get_url(sid)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/title/{sid}", summary="Get Page Title")
def web_title(sid: str):
    """Return the page title of a web session."""
    try:
        return {"ok": True, "title": web_context.get_title(sid)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
