"""Smoke tests for the web browser API router."""


class TestWeb:
    def test_create_session(self, client):
        r = client.post("/api/web/session", json={"viewport": {"width": 1280, "height": 720}})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"]
        assert data["sid"]

    def test_list_sessions(self, client):
        r = client.get("/api/web/sessions")
        assert r.status_code == 200
        assert "sessions" in r.json()

    def test_navigate_and_screenshot(self, client):
        r = client.post("/api/web/session", json={})
        sid = r.json()["sid"]

        r = client.post("/api/web/navigate", json={"sid": sid, "url": "https://example.com"})
        assert r.status_code == 200
        assert r.json()["ok"]

        r = client.get(f"/api/web/screenshot/{sid}")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"]
        assert data["image"]
        assert data["width"] > 0

        r = client.get(f"/api/web/url/{sid}")
        assert r.status_code == 200
        assert "example.com" in r.json()["url"]

        r = client.delete(f"/api/web/session/{sid}")
        assert r.status_code == 200

    def test_viewport(self, client):
        r = client.post("/api/web/session", json={})
        sid = r.json()["sid"]
        r = client.post("/api/web/viewport", json={"sid": sid, "width": 390, "height": 844})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"]
        assert data["viewport"]["width"] == 390
        client.delete(f"/api/web/session/{sid}")

    def test_screen_tree(self, client):
        r = client.post("/api/web/session", json={})
        sid = r.json()["sid"]
        client.post("/api/web/navigate", json={"sid": sid, "url": "https://example.com"})
        r = client.get(f"/api/web/screen-tree/{sid}")
        assert r.status_code == 200
        assert "tree" in r.json()
        client.delete(f"/api/web/session/{sid}")

    def test_close_missing_session(self, client):
        r = client.delete("/api/web/session/does-not-exist")
        assert r.status_code == 404
