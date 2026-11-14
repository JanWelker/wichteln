from importlib.resources import files

import pytest

from wichteln import config
from wichteln.errors import ConfigError

PEOPLE = [("p1", "Alma", "alma@example.org"), ("p2", "Bert", "bert@example.org")]


def write_participants(path, people=PEOPLE):
    text = "".join(
        f'[[participant]]\nid = "{i}"\nname = "{n}"\nemail = "{e}"\n\n' for i, n, e in people
    )
    path.write_text(text)
    return path


CONFIG = """
[smtp]
host = "smtp.example.org"
port = {port}
username = "wichteln@example.org"

[mail]
from = "{from_}"
reply_to = "wichteln@example.org"
envelope_from = "{envelope}"
"""


def write_config(path, port="465", from_="Wichteln <wichteln@example.org>", envelope="w@ex.org"):
    path.write_text(CONFIG.format(port=port, from_=from_, envelope=envelope))
    return path


def test_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("WICHTELN_HOME", str(tmp_path))
    assert config.data_dir() == tmp_path
    monkeypatch.delenv("WICHTELN_HOME")
    assert config.data_dir().name == "Wichteln"


def test_examples_accepted(tmp_path):
    examples = files("wichteln") / "examples"
    p = tmp_path / "participants.toml"
    p.write_bytes((examples / "participants.toml").read_bytes())
    c = tmp_path / "config.toml"
    c.write_bytes((examples / "config.toml").read_bytes())
    assert [x.id for x in config.load_participants(p)] == ["p1", "p2", "p3"]
    smtp, mail = config.load_config(c)
    assert smtp.port == 465
    assert mail.event_line.startswith("Bescherung")


def test_event_line_optional(tmp_path):
    _, mail = config.load_config(write_config(tmp_path / "config.toml"))
    assert mail.event_line == ""


@pytest.mark.parametrize(
    "people,match",
    [
        (PEOPLE + [("p1", "Cleo", "cleo@example.org")], "p1: duplicate 'id'"),
        (PEOPLE + [("p3", "Cleo", "ALMA@example.org")], "p3: duplicate 'email'"),
        (PEOPLE + [("P3", "Cleo", "cleo@example.org")], "entry 3: 'id'"),
        (PEOPLE + [("p3\\n", "Cleo", "cleo@example.org")], "entry 3: 'id'"),
        (PEOPLE + [("p3", "Cleo", "cleo.example.org")], "p3: 'email'"),
        (PEOPLE + [("p3", "Cleo", "cleo@example")], "p3: 'email'"),
        (PEOPLE + [("p3", "Cleo", "cl eo@example.org")], "p3: 'email'"),
        (PEOPLE[:1], "1 participants"),
        ([(f"p{i}", f"N{i}", f"n{i}@example.org") for i in range(11)], "11 participants"),
    ],
)
def test_participants_rejected(tmp_path, people, match):
    with pytest.raises(ConfigError, match=match):
        config.load_participants(write_participants(tmp_path / "participants.toml", people))


@pytest.mark.parametrize(
    "text,match",
    [
        ("x = 1\n", "list of"),
        ('[[participant]]\nid = "p1"\nemail = "a@b.org"\n', "p1: missing key 'name'"),
        ('[[participant]]\nid = 5\nname = "A"\nemail = "a@b.org"\n', "entry 1: 'id' must be"),
        ('[[participant]]\nid = "p1"\nname = "A"\nemail = "a@b.org"\nx = 1\n', "unknown key"),
    ],
)
def test_participants_shape(tmp_path, text, match):
    path = tmp_path / "participants.toml"
    path.write_text(text)
    with pytest.raises(ConfigError, match=match):
        config.load_participants(path)


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="participants.toml: not found"):
        config.load_participants(tmp_path / "participants.toml")
    with pytest.raises(ConfigError, match="config.toml: not found"):
        config.load_config(tmp_path / "config.toml")


def test_broken_toml(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[smtp\nhost = 1\n")
    with pytest.raises(ConfigError) as exc:
        config.load_config(path)
    msg = str(exc.value)
    assert "config.toml" in msg and "line" in msg and "column" in msg


def test_broken_toml_hides_names(tmp_path):
    path = tmp_path / "participants.toml"
    path.write_text("[Hildegard]\na = 1\n[Hildegard]\nb = 2\n")
    with pytest.raises(ConfigError) as exc:
        config.load_participants(path)
    assert "Hildegard" not in str(exc.value)
    assert "line" in str(exc.value)


def test_not_utf8(tmp_path):
    path = tmp_path / "participants.toml"
    path.write_bytes('[[participant]]\nname = "Jürg"\n'.encode("latin-1"))
    with pytest.raises(ConfigError, match="not valid UTF-8"):
        config.load_participants(path)


def test_folder(tmp_path):
    (tmp_path / "config.toml").mkdir()
    with pytest.raises(ConfigError, match=r"config.toml: cannot read \(IsADirectoryError\)"):
        config.load_config(tmp_path / "config.toml")


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"port": "25"}, "465 or 587"),
        ({"port": '"465"'}, "must be an integer"),
        ({"from_": "Wichteln"}, "mail.from"),
        ({"envelope": "bounce"}, "mail.envelope_from"),
    ],
)
def test_config_rejected(tmp_path, kwargs, match):
    with pytest.raises(ConfigError, match=match):
        config.load_config(write_config(tmp_path / "config.toml", **kwargs))


@pytest.mark.parametrize(
    "text,match",
    [
        ("[mail]\n", r"missing table \[smtp\]"),
        ('[smtp]\nhost = "h"\nport = 465\n[mail]\n', "smtp.username"),
        ('[smtp]\nhost = "h"\nusername = "u"\n[mail]\n', "smtp.port"),
        ('[smtp]\nhost = 1\nport = 465\nusername = "u"\n[mail]\n', "'smtp.host' must be"),
    ],
)
def test_config_missing_keys(tmp_path, text, match):
    path = tmp_path / "config.toml"
    path.write_text(text)
    with pytest.raises(ConfigError, match=match):
        config.load_config(path)


def test_starttls_port_accepted(tmp_path):
    smtp, _ = config.load_config(write_config(tmp_path / "config.toml", port="587"))
    assert smtp.port == 587
