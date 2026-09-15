from pathlib import Path

from labwatch_agent.config import AgentConfig, read_state, write_state


def test_read_state_flattens_agent_table(tmp_path: Path):
    cfg = AgentConfig(state_dir=str(tmp_path))
    (tmp_path / "state.toml").write_text(
        "\n".join(
            [
                "[agent]",
                'agent_id = "abc-123"',
                'agent_secret = "sekrit"',
                'machine_id = "mid-1"',
                "approved = true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    state = read_state(cfg)
    assert state.get("agent_id") == "abc-123"
    assert state.get("machine_id") == "mid-1"
    assert state.get("agent_secret") == "sekrit"
    assert state.get("approved") is True
    assert "agent" not in state or not isinstance(state.get("agent"), dict)


def test_write_state_roundtrip_is_flat(tmp_path: Path):
    cfg = AgentConfig(state_dir=str(tmp_path))
    write_state(cfg, {"agent_id": "id-9", "agent_secret": "s", "machine_id": "m9", "approved": True})
    text = cfg.state_file.read_text(encoding="utf-8")
    assert "[agent]" in text
    assert 'agent_id = "id-9"' in text
    state = read_state(cfg)
    assert state["agent_id"] == "id-9"
    assert state["machine_id"] == "m9"
    assert state["approved"] is True
