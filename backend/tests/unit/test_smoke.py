from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.api import settings as settings_api


def test_health():
    client = TestClient(app)
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_settings_defaults(tmp_path, monkeypatch):
    # 隔离真实 data/：默认值断言不应受本地使用产生的 settings.json 影响
    monkeypatch.setattr(settings_api, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(settings_api, "SETTINGS_PATH", str(tmp_path / "settings.json"))
    client = TestClient(app)
    res = client.get("/api/settings")
    assert res.status_code == 200
    body = res.json()
    assert body["alignModel"] == "base"
    assert body["defaultSpeed"] == 1.0
    assert body["showTranslationDefault"] is True
    assert body["llm"]["enabled"] is False
