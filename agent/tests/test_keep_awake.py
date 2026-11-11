from labwatch_agent import keep_awake


def test_apply_keep_awake_does_not_raise(monkeypatch):
    monkeypatch.setattr(keep_awake, "_apply_linux", lambda: ["ok"])
    monkeypatch.setattr(keep_awake, "_apply_windows", lambda: ["ok"])
    keep_awake.apply_keep_awake()


def test_apply_keep_awake_swallows_errors(monkeypatch):
    def boom():
        raise RuntimeError("nope")

    monkeypatch.setattr(keep_awake, "_apply_linux", boom)
    monkeypatch.setattr(keep_awake, "_apply_windows", boom)
    keep_awake.apply_keep_awake()
