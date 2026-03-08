import pytest

from gateflow.cli import main


def test_cli_help_flag(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "usage: gateflow" in capsys.readouterr().out
