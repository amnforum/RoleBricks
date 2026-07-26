from __future__ import annotations

import time


SCENE_PROMPT = (
    "I want to be a startup founder negotiating a difficult partnership with "
    "Aarav Mehta while an independent advisor challenges both sides."
)


def _create_scene(client):
    response = client.post("/api/worlds/draft", json={"prompt": SCENE_PROMPT, "locale": "en-IN"})
    assert response.status_code == 201, response.text
    return response.json()


def _wait_until_ready(client, scene_id: str):
    deadline = time.monotonic() + 8
    latest = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/worlds/{scene_id}")
        assert response.status_code == 200, response.text
        latest = response.json()
        if latest["status"] == "ready":
            return latest
        if latest.get("preparation_job", {}).get("status") == "failed":
            raise AssertionError(latest["preparation_job"])
        time.sleep(0.05)
    raise AssertionError(f"Scene did not become ready: {latest}")


def test_scene_draft_is_editable_and_does_not_start_expensive_work(client):
    scene = _create_scene(client)

    assert scene["status"] == "blueprint"
    assert scene["active_manifest_version"] == 1
    assert scene["preparation"]["research_started"] is False
    assert scene["preparation_job"] is None
    assert 1 <= len([item for item in scene["manifest"]["ai_characters"] if item["selected"]]) <= 3
    assert any(not item["selected"] for item in scene["manifest"]["ai_characters"])


def test_blueprint_versions_and_revert_are_auditable(client):
    scene = _create_scene(client)
    scene_id = scene["id"]
    response = client.patch(
        f"/api/worlds/{scene_id}/blueprint",
        json={
            "expected_version": 1,
            "pressure": "high_pressure",
            "change_reason": "Practice under pressure",
        },
    )
    assert response.status_code == 200, response.text
    edited = response.json()
    assert edited["active_manifest_version"] == 2
    assert edited["manifest"]["pressure"] == "high_pressure"
    assert "behavior" in edited["versions"][-1]["invalidated_components"]

    response = client.post(
        f"/api/worlds/{scene_id}/revert",
        json={"expected_version": 2, "target_version": 1},
    )
    assert response.status_code == 200, response.text
    reverted = response.json()
    assert reverted["active_manifest_version"] == 3
    assert reverted["manifest"]["pressure"] == "realistic"
    assert reverted["versions"][-1]["change_reason"] == "Reverted to blueprint 1"


def test_confirm_prepares_cast_voice_memory_and_live_turn(client):
    scene = _create_scene(client)
    scene_id = scene["id"]

    response = client.post(
        f"/api/worlds/{scene_id}/confirm",
        json={"expected_version": scene["active_manifest_version"]},
    )
    assert response.status_code == 202, response.text
    ready = _wait_until_ready(client, scene_id)

    assert len(ready["agents"]) == 2
    assert ready["turns"][0]["turn_data"]["opening"] is True
    assert ready["turns"][0]["audio_url"]
    assert all(agent["voice_profile"]["sample_audio_url"] for agent in ready["agents"])
    assert ready["preparation"]["character_count"] == 2

    response = client.post(f"/api/worlds/{scene_id}/enter")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "live"

    response = client.post(
        f"/api/worlds/{scene_id}/turns",
        json={"text": "I can prove this partnership protects both sides."},
    )
    assert response.status_code == 200, response.text
    active = response.json()
    assert active["turns"][-1]["speaker_type"] == "agent"
    assert active["turns"][-1]["action"] in {
        "answer",
        "challenge",
        "interrupt",
        "evade",
        "probe",
        "joke",
        "correct",
        "accuse",
        "concede",
        "refuse",
        "redirect",
        "end",
    }
    audio = client.get(active["turns"][-1]["audio_url"])
    assert audio.status_code == 200
    assert audio.headers["content-type"].startswith("audio/wav")


def test_more_than_three_selected_characters_is_rejected(client):
    scene = _create_scene(client)
    characters = scene["manifest"]["ai_characters"]
    while len(characters) < 4:
        duplicate = dict(characters[-1])
        duplicate["key"] = f"candidate-{len(characters) + 1}"
        duplicate["name"] = f"Candidate {len(characters) + 1}"
        characters.append(duplicate)
    for character in characters[:4]:
        character["selected"] = True

    response = client.patch(
        f"/api/worlds/{scene['id']}/blueprint",
        json={
            "expected_version": 1,
            "ai_characters": characters,
            "change_reason": "Try four agents",
        },
    )
    assert response.status_code == 422


def test_stale_blueprint_version_is_rejected(client):
    scene = _create_scene(client)
    response = client.patch(
        f"/api/worlds/{scene['id']}/blueprint",
        json={
            "expected_version": 99,
            "pressure": "supportive",
            "change_reason": "Stale edit",
        },
    )
    assert response.status_code == 422
    assert response.json()["details"]["current_version"] == 1

