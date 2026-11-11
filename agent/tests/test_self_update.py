from pathlib import Path
from unittest.mock import patch

import pytest

from labwatch_agent.self_update import (
    BACKUP_NAME,
    NEXT_NAME,
    _read_version,
    apply_pack,
    install_prefix,
)


def test_read_version_from_init(tmp_path: Path):
    init = tmp_path / "__init__.py"
    init.write_text('"""x"""\n\n__version__ = "1.2.3"\n', encoding="utf-8")
    assert _read_version(init) == "1.2.3"


def test_install_prefix_is_parent_of_package():
    prefix = install_prefix()
    assert (prefix / "labwatch_agent" / "self_update.py").is_file()


def test_apply_pack_rolls_back_on_bad_pack(tmp_path: Path, monkeypatch):
    prefix = tmp_path / "opt"
    pkg = prefix / "labwatch_agent"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    (pkg / "keep_me.txt").write_text("old", encoding="utf-8")
    venv_py = prefix / "venv" / "bin" / "python"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text("#!/bin/sh\n", encoding="utf-8")
    venv_py.chmod(0o755)

    monkeypatch.setattr("labwatch_agent.self_update.install_prefix", lambda: prefix)

    with pytest.raises(Exception):
        apply_pack(b"not-a-tarball")

    assert (pkg / "keep_me.txt").read_text(encoding="utf-8") == "old"
    assert "1.0.0" in (pkg / "__init__.py").read_text(encoding="utf-8")
    assert not (prefix / BACKUP_NAME).exists()


def test_apply_pack_rolls_back_when_pip_fails(tmp_path: Path, monkeypatch):
    import io
    import tarfile

    prefix = tmp_path / "opt"
    pkg = prefix / "labwatch_agent"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    (pkg / "keep_me.txt").write_text("old", encoding="utf-8")
    venv_py = prefix / "venv" / "bin" / "python"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text("#!/bin/sh\n", encoding="utf-8")
    venv_py.chmod(0o755)

    monkeypatch.setattr("labwatch_agent.self_update.install_prefix", lambda: prefix)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        def add(name: str, data: bytes):
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

        add("labwatch_agent/__init__.py", b'__version__ = "9.9.9"\n')
        add("requirements.txt", b"unused==0\n")
        add("wheels/dummy.whl", b"PK\x03\x04")
    pack = buf.getvalue()

    with patch("labwatch_agent.self_update.subprocess.run", side_effect=RuntimeError("pip boom")):
        with pytest.raises(RuntimeError, match="pip boom"):
            apply_pack(pack)

    assert (pkg / "keep_me.txt").read_text(encoding="utf-8") == "old"
    assert "1.0.0" in (pkg / "__init__.py").read_text(encoding="utf-8")


def _make_pack(version: str = "1.1.66") -> bytes:
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        def add(name: str, data: bytes):
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

        add("labwatch_agent/__init__.py", f'__version__ = "{version}"\n'.encode())
        add("labwatch_agent/new_file.txt", b"staged")
        add("requirements.txt", b"unused==0\n")
        add("wheels/dummy.whl", b"PK\x03\x04")
    return buf.getvalue()


def test_apply_pack_swaps_live_and_keeps_backup(tmp_path: Path, monkeypatch):
    """After verify, live tree is swapped immediately; .prev kept for rollback."""
    prefix = tmp_path / "opt" / "labwatch-agent"
    pkg = prefix / "labwatch_agent"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    (pkg / "keep_me.txt").write_text("live", encoding="utf-8")
    venv_py = prefix / "venv" / "bin" / "python"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text("#!/bin/sh\n", encoding="utf-8")
    venv_py.chmod(0o755)

    monkeypatch.setattr("labwatch_agent.self_update.install_prefix", lambda: prefix)
    monkeypatch.setattr("labwatch_agent.self_update._is_windows", lambda: False)

    def fake_run(cmd, **kwargs):
        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    with patch("labwatch_agent.self_update.subprocess.run", side_effect=fake_run):
        ver = apply_pack(_make_pack("1.1.66"), target_version="1.1.66")

    assert ver == "1.1.66"
    assert not (prefix / NEXT_NAME).exists()
    assert "1.1.66" in (pkg / "__init__.py").read_text(encoding="utf-8")
    assert (pkg / "new_file.txt").read_text(encoding="utf-8") == "staged"
    assert not (pkg / "keep_me.txt").exists()
    assert (prefix / BACKUP_NAME).is_dir()
    assert "1.0.0" in (prefix / BACKUP_NAME / "__init__.py").read_text(encoding="utf-8")


def test_apply_pack_windows_swaps_live_and_keeps_backup(tmp_path: Path, monkeypatch):
    """Windows also swaps after verify; running process keeps old modules in memory."""
    prefix = tmp_path / "Program Files" / "LabWatch Agent"
    pkg = prefix / "labwatch_agent"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    (pkg / "keep_me.txt").write_text("live", encoding="utf-8")
    venv_py = prefix / "venv" / "Scripts" / "python.exe"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_bytes(b"MZ")

    monkeypatch.setattr("labwatch_agent.self_update.install_prefix", lambda: prefix)
    monkeypatch.setattr("labwatch_agent.self_update._is_windows", lambda: True)

    def fake_run(cmd, **kwargs):
        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    with patch("labwatch_agent.self_update.subprocess.run", side_effect=fake_run):
        ver = apply_pack(_make_pack("1.1.66"), target_version="1.1.66")

    assert ver == "1.1.66"
    assert not (prefix / NEXT_NAME).exists()
    assert "1.1.66" in (pkg / "__init__.py").read_text(encoding="utf-8")
    assert (prefix / BACKUP_NAME).is_dir()
