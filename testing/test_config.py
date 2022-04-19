import re
import textwrap

import pytest

from setuptools_scm.config import Configuration


@pytest.mark.parametrize(
    "tag, expected_version",
    [
        ("apache-arrow-0.9.0", "0.9.0"),
        ("arrow-0.9.0", "0.9.0"),
        ("arrow-0.9.0-rc", "0.9.0-rc"),
        ("arrow-1", "1"),
        ("arrow-1+", "1"),
        ("arrow-1+foo", "1"),
        ("arrow-1.1+foo", "1.1"),
        ("v1.1", "v1.1"),
        ("V1.1", "V1.1"),
    ],
)
def test_tag_regex(tag, expected_version):
    config = Configuration()
    match = config.tag_regex.match(tag)
    assert match
    version = match.group("version")
    assert version == expected_version


def test_config_from_pyproject(tmpdir):
    fn = tmpdir / "pyproject.toml"
    fn.write_text(
        textwrap.dedent(
            """
            [tool.setuptools_scm]
            root = "../.."

            [project]
            description = "Factory ⸻ A code generator 🏭"
            authors = [{name = "Łukasz Langa"}]
            """
        ),
        encoding="utf-8",
    )
    config = Configuration.from_file(str(fn))
    assert config
    assert config.root == "../.."


def test_config_regex_init():
    tag_regex = re.compile(r"v(\d+)")
    conf = Configuration(tag_regex=tag_regex)
    assert conf.tag_regex is tag_regex
