from pathlib import Path
from unittest.mock import patch

import pytest

from labwatch_agent.self_update import BACKUP_NAME, _read_version, apply_pack, install_prefix


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
