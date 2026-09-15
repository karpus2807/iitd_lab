from labwatch_agent.netaddr import _clean_ip, primary_ip


def test_skips_loopback_and_picks_lan():
    assert _clean_ip("127.0.0.1") is None
    assert _clean_ip("::1") is None
    assert primary_ip(["8.8.8.8", "10.0.0.5"]) == "10.0.0.5"
