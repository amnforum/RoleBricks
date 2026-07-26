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
    allowed = {"/health", "/ready", "/", "/admin", "/api/transcribe", "/api/admin/overview"}
    assert all(path.startswith("/api/worlds") or path in allowed for path in paths)


def test_ready_and_admin_never_expose_credentials_or_resource_ids(client):
    ready = client.get("/ready")
    assert ready.status_code == 200
    serialized_ready = ready.text.casefold()
    for sensitive in (
        "audio_data_dir",
        "serving_endpoint",
        "search_index",
        "warehouse_id",
        "experiment_id",
        "api_key",
        "test-key",
    ):
        assert sensitive not in serialized_ready

    page = client.get("/admin")
    assert page.status_code == 200
    assert "RoleBricks operations" in page.text
    overview = client.get("/api/admin/overview")
    assert overview.status_code == 200
    body = overview.json()
    assert body["viewer"] == "local-admin"
    assert body["providers"]
    assert "usage" in body and "latency" in body and "queue" in body
    assert "test-key" not in overview.text
