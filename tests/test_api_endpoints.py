from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import create_app


def test_api_tracked_items_flow(settings):
    app = create_app()
    client = TestClient(app)

    headers = {
        "X-Dev-Telegram-Id": "10001",
        "X-Dev-Username": "tester",
        "X-Dev-Full-Name": "Test User",
    }

    me = client.get("/api/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["telegram_user_id"] == 10001

    created = client.post(
        "/api/tracked-items",
        headers=headers,
        json={
            "title": "API item",
            "map_link": "https://example.com/map",
            "is_active": False,
            "run_initial_check": False,
        },
    )
    assert created.status_code == 200
    payload = created.json()
    item_id = payload["item"]["id"]

    listed = client.get("/api/tracked-items", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    details = client.get(f"/api/tracked-items/{item_id}", headers=headers)
    assert details.status_code == 200
    assert details.json()["item"]["id"] == item_id

    patched = client.patch(
        f"/api/tracked-items/{item_id}",
        headers=headers,
        json={"is_active": True, "title": "Updated title"},
    )
    assert patched.status_code == 200
    assert patched.json()["is_active"] is True
    assert patched.json()["title"] == "Updated title"

    snapshots = client.get(f"/api/tracked-items/{item_id}/snapshots", headers=headers)
    assert snapshots.status_code == 200
    assert snapshots.json() == []

    events = client.get(f"/api/tracked-items/{item_id}/events", headers=headers)
    assert events.status_code == 200
    assert events.json() == []

    zone_diff_missing = client.get(f"/api/tracked-items/{item_id}/snapshots/999/zone-diff", headers=headers)
    assert zone_diff_missing.status_code == 404

    app.state.mvp_service.run_manual_check = lambda telegram_user_id, tracked_item_id: {
        "tracked_item_id": tracked_item_id,
        "checked_at": "2026-01-01T00:00:00+00:00",
        "status": "success",
        "snapshot_id": 11,
        "zone_count": 2,
        "added_count": 1,
        "removed_count": 0,
        "event_id": 7,
        "error_message": None,
        "event_type": "new_zones",
        "tracked_item_title": "Updated title",
        "diff_image_path": None,
    }

    checked = client.post(f"/api/tracked-items/{item_id}/check", headers=headers)
    assert checked.status_code == 200
    assert checked.json()["event_id"] == 7

    deleted = client.delete(f"/api/tracked-items/{item_id}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    listed_after_delete = client.get("/api/tracked-items", headers=headers)
    assert listed_after_delete.status_code == 200
    assert listed_after_delete.json() == []
