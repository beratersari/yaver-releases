"""Address checks for the release site's Analytics GET."""

from __future__ import annotations

import socket

from yaver_releases.install_fetch import analytics_url, fetch_install_analytics


def test_only_a_callable_ip_becomes_a_url():
    assert analytics_url("127.0.0.1") == "http://127.0.0.1:8080/api/analytics/install"
    assert analytics_url("10.1.2.3") == "http://10.1.2.3:8080/api/analytics/install"
    assert analytics_url("::1") == "http://[::1]:8080/api/analytics/install"
    assert analytics_url("evil.test") == ""
    assert analytics_url("127.0.0.1:8080") == ""
    assert analytics_url("http://127.0.0.1/api/analytics") == ""
    assert analytics_url("169.254.169.254") == ""
    assert analytics_url("0.0.0.0") == ""


def test_blocked_addresses_do_not_open_a_client(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("opened a client")

    monkeypatch.setattr("yaver_releases.install_fetch.httpx.Client", explode)
    usage, error = fetch_install_analytics("169.254.169.254")
    assert usage is None
    assert error == "This address is not requested."
    usage, error = fetch_install_analytics("not-an-ip")
    assert usage is None
    assert error == "This address is not an IP address."


def test_a_closed_port_is_reported_without_using_8080(monkeypatch):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    assert port != 8080
    monkeypatch.setattr("yaver_releases.install_fetch.INSTALL_ANALYTICS_PORT", port)
    usage, error = fetch_install_analytics("127.0.0.1")
    assert usage is None
    assert error == f"Could not reach this install on port {port}."
