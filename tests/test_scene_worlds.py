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
    assert ready["turns"] == []
    assert all(agent["voice_profile"]["sample_audio_url"] for agent in ready["agents"])
    assert ready["preparation"]["character_count"] == 2

    response = client.post(f"/api/worlds/{scene_id}/enter")
    assert response.status_code == 200, response.text
    entered = response.json()
    assert entered["status"] == "live"
    assert entered["turns"] == []

    response = client.post(
        f"/api/worlds/{scene_id}/turns",
        json={"text": "I can prove this partnership protects both sides."},
    )
    assert response.status_code == 200, response.text
    active = response.json()
    assert active["turns"][-1]["speaker_type"] == "agent"
    assert active["turns"][-1]["turn_data"]["latency_ms"] >= 0
    assert active["turns"][-1]["turn_data"]["panel_plan"]["turns"][0]["should_speak"] is True
    assert set(active["turns"][-1]["turn_data"]["latency_breakdown_ms"]) == {
        "research",
        "retrieval",
        "reasoning",
        "voice",
    }
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


def test_more_than_five_selected_ai_respondents_is_rejected(client):
    scene = _create_scene(client)
    characters = scene["manifest"]["ai_characters"]
    while len(characters) < 6:
        duplicate = dict(characters[-1])
        duplicate["key"] = f"candidate-{len(characters) + 1}"
        duplicate["name"] = f"Candidate {len(characters) + 1}"
        characters.append(duplicate)
    for character in characters[:6]:
        character["selected"] = True

    response = client.patch(
        f"/api/worlds/{scene['id']}/blueprint",
        json={
            "expected_version": 1,
            "ai_characters": characters,
            "change_reason": "Try six AI respondents",
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


def test_public_figure_scene_is_labelled_and_forces_an_original_voice(client):
    response = client.post(
        "/api/worlds/draft",
        json={
            "prompt": (
                "I want a Hinglish interview practice scene with Shah Rukh Khan, "
                "a Bollywood celebrity, before tomorrow's entertainment interview."
            ),
            "locale": "en-IN",
        },
    )
    assert response.status_code == 201, response.text
    primary = response.json()["manifest"]["ai_characters"][0]
    assert primary["identity_kind"] == "public_figure"
    assert primary["voice"]["identity_mode"] == "distinct_synthetic"
    assert primary["voice"]["requested_identity"] == ""
    assert "simulation" in primary["portrayal_notice"].casefold()
    assert primary["speech"]["language"] == "Hinglish"


def test_identical_scene_restores_prepared_pack_without_copying_conversation(client):
    first = _create_scene(client)
    first_id = first["id"]
    confirmed = client.post(
        f"/api/worlds/{first_id}/confirm",
        json={"expected_version": first["active_manifest_version"]},
    )
    assert confirmed.status_code == 202, confirmed.text
    _wait_until_ready(client, first_id)
    assert client.post(f"/api/worlds/{first_id}/enter").status_code == 200
    first_turn = client.post(
        f"/api/worlds/{first_id}/turns",
        json={"text": "This sentence must remain private to the first scene."},
    )
    assert first_turn.status_code == 200, first_turn.text

    second = _create_scene(client)
    second_id = second["id"]
    confirmed = client.post(
        f"/api/worlds/{second_id}/confirm",
        json={"expected_version": second["active_manifest_version"]},
    )
    assert confirmed.status_code == 202, confirmed.text
    restored = _wait_until_ready(client, second_id)
    assert restored["preparation"]["cache_hit"] is True
    assert restored["preparation_job"]["job_data"]["cache_hit"] is True
    assert restored["turns"] == []


def test_scene_management_actions_keep_or_remove_the_right_records(client):
    scene = _create_scene(client)
    scene_id = scene["id"]
    confirmed = client.post(
        f"/api/worlds/{scene_id}/confirm",
        json={"expected_version": scene["active_manifest_version"]},
    )
    assert confirmed.status_code == 202, confirmed.text
    ready = _wait_until_ready(client, scene_id)
    assert ready["turns"] == []
    assert client.post(f"/api/worlds/{scene_id}/enter").status_code == 200
    turn = client.post(
        f"/api/worlds/{scene_id}/turns",
        json={"text": "Please challenge my answer with one practical objection."},
    )
    assert turn.status_code == 200, turn.text
    active = turn.json()
    assert len(active["turns"]) == 2
    assert len(active["agents"]) == 2

    cleared_memory = client.delete(f"/api/worlds/{scene_id}/memories")
    assert cleared_memory.status_code == 200, cleared_memory.text
    assert len(cleared_memory.json()["agents"]) == 2
    assert len(cleared_memory.json()["turns"]) == 2

    cleared_history = client.delete(f"/api/worlds/{scene_id}/history")
    assert cleared_history.status_code == 200, cleared_history.text
    history_payload = cleared_history.json()
    assert history_payload["turns"] == []
    assert len(history_payload["agents"]) == 2

    deleted = client.delete(f"/api/worlds/{scene_id}")
    assert deleted.status_code == 204, deleted.text
    missing = client.get(f"/api/worlds/{scene_id}")
    assert missing.status_code == 404
