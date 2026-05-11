from agent.api import app


def test_run_sse_response_is_documented():
    openapi = app.openapi()

    run_200 = openapi["paths"]["/api/run"]["post"]["responses"]["200"]
    assert "text/event-stream" in run_200["content"]


def test_run_json_debug_endpoint_is_documented():
    openapi = app.openapi()

    assert "/api/run-json" in openapi["paths"]
