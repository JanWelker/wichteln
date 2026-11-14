import wichteln
from wichteln import errors


def test_version():
    assert isinstance(wichteln.__version__, str)
    assert wichteln.__version__


def test_exit_codes():
    assert errors.WichtelnError.exit_code == 1
    assert errors.UsageError.exit_code == 1
    assert errors.ConfigError.exit_code == 1
    assert errors.SendFailures.exit_code == 2
    assert errors.StateError.exit_code == 3
