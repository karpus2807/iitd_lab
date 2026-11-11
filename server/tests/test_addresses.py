from app.services.addresses import lan_wan_ips, normalize_ips, primary_ip


def test_loopback_never_used_as_identity_or_primary():
    assert normalize_ips(["127.0.0.1", "::1", "10.0.1.42", "10.0.1.42"]) == ["10.0.1.42"]
    assert primary_ip(["127.0.0.1"]) is None
    assert primary_ip(["169.254.12.3", "192.168.10.44"]) == "192.168.10.44"


def test_lan_switch_prefers_new_private_ipv4():
    before = primary_ip(["192.168.1.20"])
    after = primary_ip(["10.32.4.88", "fe80::1"])
    assert before == "192.168.1.20"
    assert after == "10.32.4.88"


def test_lan_wan_split():
    lan, wan = lan_wan_ips(["10.1.2.3", "203.0.113.9", "fe80::1"])
    assert lan == "10.1.2.3"
    assert wan == "203.0.113.9"
    assert lan_wan_ips([], "192.168.0.5") == ("192.168.0.5", None)
    assert lan_wan_ips(["8.8.8.8"]) == (None, "8.8.8.8")
