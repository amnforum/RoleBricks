from __future__ import annotations


def test_api_error_response_shape(client):
    response = client.post("/api/worlds/draft", json={})
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "Invalid request"
    assert "details" in body


def test_health_and_ready(client):
    assert client.get("/health").json()["status"] == "ok"
    ready = client.get("/ready").json()
    assert ready["ready"] is True
    assert ready["provider"] == "mock-tts"
    assert ready["scene_compiler_ready"] is True
    assert ready["scene_research_ready"] is True
    assert ready["scene_retrieval_ready"] is True
    assert ready["scene_max_agents"] == 3


def test_root_renders_the_open_ended_scene_workflow(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="scenePromptForm"' in response.text
    assert "Step into any situation" in response.text
    assert "Build this scene" in response.text
    assert "Choose up to three characters" in response.text
    assert "RoleBricks" in response.text
    assert "/static/images/rolebricks-logo.webp" in response.text
    assert "/static/images/rolebricks-favicon.png" in response.text
    assert "Living character engine" not in response.text
    assert "Voice lab" not in response.text


def test_legacy_voice_studio_is_not_shipped(client):
    assert client.get("/voice-studio").status_code == 404
    paths = client.get("/openapi.json").json()["paths"]
    assert all(path.startswith("/api/worlds") or path in {"/health", "/ready", "/", "/api/transcribe"} for path in paths)
