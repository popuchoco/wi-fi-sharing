import ast
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import frontend.main as frontend


def test_local_ui_loads_without_agent_engine_or_adc(monkeypatch):
    monkeypatch.delenv("AGENT_ENGINE_RESOURCE_NAME", raising=False)
    monkeypatch.setattr(frontend, "_creds", None)

    def unexpected_adc(*_args, **_kwargs):
        pytest.fail("local UI must not initialize Google ADC")

    monkeypatch.setattr(frontend.google.auth, "default", unexpected_adc)
    client = TestClient(frontend.app)

    page = client.get("/")
    status = client.get("/auth/status")

    assert page.status_code == 200
    assert "本機分享" in page.text
    assert "使用說明" in page.text
    assert status.status_code == 200
    assert status.json()["help_available"] is False
    assert frontend._creds is None


def test_help_endpoint_is_only_required_when_chat_is_used(monkeypatch):
    monkeypatch.delenv("AGENT_ENGINE_RESOURCE_NAME", raising=False)

    with pytest.raises(HTTPException) as error:
        frontend._agent_endpoints()

    assert error.value.status_code == 503
    assert "本機 Wi-Fi 分享仍可直接使用" in error.value.detail


def test_help_agent_is_configured_without_tools():
    agent_source = Path("app/agent.py").read_text(encoding="utf-8")
    module = ast.parse(agent_source)
    root_agent = next(
        node.value
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "root_agent"
            for target in node.targets
        )
    )

    assert isinstance(root_agent, ast.Call)
    tools = next(keyword.value for keyword in root_agent.keywords if keyword.arg == "tools")
    assert isinstance(tools, ast.List)
    assert tools.elts == []
