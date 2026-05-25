"""CLI smoke tests (no LLM tokens needed)."""

import asyncio
import re
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

import carapace.cli as cli_module
from carapace.cli import _render_escalation_request, _replay_history, app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "carapace" in _strip_ansi(result.output)


def test_chat_help():
    result = runner.invoke(app, ["chat", "--help"])
    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    assert "--session" in output
    assert "--server" in output
    assert "--user" in output
    assert "--password" in output


@pytest.mark.parametrize(
    ("inputs", "expected_decision", "expected_message"),
    [
        (["a"], "allow", None),
        (["allow"], "allow", None),
        (["d", ""], "deny", None),
        (["deny", "blocked by user"], "deny", "blocked by user"),
        (["x", "not safe enough"], "deny", "not safe enough"),
    ],
)
def test_proxy_approval_choice_mapping(inputs: list[str], expected_decision: str, expected_message: str | None):
    with patch("carapace.cli.console.input", side_effect=inputs):
        decision, message = asyncio.run(_render_escalation_request({"domain": "example.com", "command": "curl"}))
    assert decision == expected_decision
    assert message == expected_message


class _FakeHttpResponse:
    def __init__(self, payload: object):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


def test_chat_list_fetches_all_session_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter(
        [
            {
                "items": [
                    {
                        "session_id": "session-1",
                        "title": "First",
                        "created_at": "2026-05-06T10:00:00",
                        "last_active": "2026-05-06T10:01:00",
                        "message_count": 3,
                    }
                ],
                "has_more": True,
                "next_cursor": "1",
            },
            {
                "items": [
                    {
                        "session_id": "session-2",
                        "title": "Second",
                        "created_at": "2026-05-06T10:02:00",
                        "last_active": "2026-05-06T10:03:00",
                        "message_count": 7,
                    }
                ],
                "has_more": False,
                "next_cursor": None,
            },
        ]
    )
    seen_params: list[dict[str, str]] = []

    class _Cookie:
        name = "carapace_session"
        value = "session-token"

    class _Cookies:
        def __init__(self) -> None:
            self.jar = [_Cookie()]

    class _FakeClient:
        def __init__(self, base_url: str):
            assert base_url == "http://example.test"
            self.cookies = _Cookies()

        def post(self, url: str, *, json: dict[str, str] | None = None):
            assert url == "/api/auth/login"
            assert json == {"username": "thies", "password": "secret"}
            return _FakeHttpResponse({"user": {"username": "thies"}})

        def get(self, url: str, *, params: dict[str, str] | None = None):
            assert url == "/api/sessions"
            seen_params.append(dict(params or {}))
            return _FakeHttpResponse(next(responses))

        def close(self) -> None:
            return None

    monkeypatch.setattr(cli_module.httpx, "Client", _FakeClient)

    result = runner.invoke(
        app,
        ["chat", "--server", "http://example.test", "--user", "thies", "--password", "secret", "--list"],
    )

    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    assert "session-1" in output
    assert "session-2" in output
    assert seen_params == [
        {"include_message_count": "true", "limit": "200"},
        {"include_message_count": "true", "limit": "200", "cursor": "1"},
    ]


def test_replay_history_uses_authenticated_client(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_requests: list[tuple[str, dict[str, int]]] = []

    class _FakeClient:
        def get(self, url: str, *, params: dict[str, int] | None = None):
            seen_requests.append((url, dict(params or {})))
            return _FakeHttpResponse([{"role": "user", "content": "hello"}])

    def fail_module_get(*args: object, **kwargs: object) -> None:
        raise AssertionError("module-level httpx.get should not be used")

    monkeypatch.setattr(cli_module.httpx, "get", fail_module_get)

    _replay_history(_FakeClient(), "session-1", 25)  # type: ignore[arg-type]

    assert seen_requests == [("/api/sessions/session-1/history", {"limit": 25})]
