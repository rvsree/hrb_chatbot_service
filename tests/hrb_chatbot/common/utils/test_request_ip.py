from unittest.mock import MagicMock

from src.hrb_chatbot.common.utils.request_ip import resolve_client_ip


def _fake_request(forwarded_for: str | None, client_host: str | None):
    request = MagicMock()
    request.headers.get.return_value = forwarded_for
    if client_host is None:
        request.client = None
    else:
        request.client.host = client_host
    return request


def test_resolve_client_ip_uses_the_first_x_forwarded_for_entry():
    request = _fake_request("203.0.113.7, 10.0.0.1, 10.0.0.2", "10.0.0.1")
    assert resolve_client_ip(request) == "203.0.113.7"


def test_resolve_client_ip_strips_whitespace_around_the_first_entry():
    request = _fake_request(" 203.0.113.7 , 10.0.0.1", "10.0.0.1")
    assert resolve_client_ip(request) == "203.0.113.7"


def test_resolve_client_ip_falls_back_to_request_client_host_when_header_missing():
    request = _fake_request(None, "127.0.0.1")
    assert resolve_client_ip(request) == "127.0.0.1"


def test_resolve_client_ip_falls_back_to_request_client_host_when_header_empty():
    request = _fake_request("", "127.0.0.1")
    assert resolve_client_ip(request) == "127.0.0.1"


def test_resolve_client_ip_returns_none_when_no_header_and_no_client():
    request = _fake_request(None, None)
    assert resolve_client_ip(request) is None
