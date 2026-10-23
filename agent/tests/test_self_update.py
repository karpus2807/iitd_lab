from pathlib import Path

from labwatch_agent.self_update import _read_version, install_prefix


def test_read_version_from_init(tmp_path: Path):
    init = tmp_path / "__init__.py"
    init.write_text('"""x"""\n\n__version__ = "1.2.3"\n', encoding="utf-8")
    assert _read_version(init) == "1.2.3"


def test_install_prefix_is_parent_of_package():
    prefix = install_prefix()
    assert (prefix / "labwatch_agent" / "self_update.py").is_file()
