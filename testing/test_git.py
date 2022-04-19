import os
import sys
from datetime import date
from datetime import datetime
from datetime import timezone
from os.path import join as opj
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from setuptools_scm import git
from setuptools_scm import integration
from setuptools_scm import NonNormalizedVersion
from setuptools_scm.file_finder_git import git_find_files
from setuptools_scm.utils import do
from setuptools_scm.utils import has_command


pytestmark = pytest.mark.skipif(
    not has_command("git", warn=False), reason="git executable not found"
)


@pytest.fixture
def wd(wd, monkeypatch):
    monkeypatch.delenv("HOME", raising=False)
    wd("git init")
    wd("git config user.email test@example.com")
    wd('git config user.name "a test"')
    wd.add_command = "git add ."
    wd.commit_command = "git commit -m test-{reason}"
    return wd


@pytest.mark.parametrize(
    "given, tag, number, node, dirty",
    [
        ("3.3.1-rc26-0-g9df187b", "3.3.1-rc26", 0, "g9df187b", False),
        ("17.33.0-rc-17-g38c3047c0", "17.33.0-rc", 17, "g38c3047c0", False),
    ],
)
def test_parse_describe_output(given, tag, number, node, dirty):
    parsed = git._git_parse_describe(given)
    assert parsed == (tag, number, node, dirty)


def test_root_relative_to(tmpdir, wd, monkeypatch):
    monkeypatch.delenv("SETUPTOOLS_SCM_DEBUG")
    p = wd.cwd.joinpath("sub/package")
    p.mkdir(parents=True)
    p.joinpath("setup.py").write_text(
        """from setuptools import setup
setup(use_scm_version={"root": "../..",
                       "relative_to": __file__})
"""
    )
    res = do((sys.executable, "setup.py", "--version"), p)
    assert res == "0.1.dev0"


def test_root_search_parent_directories(tmpdir, wd, monkeypatch):
    monkeypatch.delenv("SETUPTOOLS_SCM_DEBUG")
    p = wd.cwd.joinpath("sub/package")
    p.mkdir(parents=True)
    p.joinpath("setup.py").write_text(
        """from setuptools import setup
setup(use_scm_version={"search_parent_directories": True})
"""
    )
    res = do((sys.executable, "setup.py", "--version"), p)
    assert res == "0.1.dev0"


def test_git_gone(wd, monkeypatch):
    monkeypatch.setenv("PATH", str(wd.cwd / "not-existing"))
    with pytest.raises(EnvironmentError, match="'git' was not found"):
        git.parse(str(wd.cwd), git.DEFAULT_DESCRIBE)


@pytest.mark.issue("https://github.com/pypa/setuptools_scm/issues/298")
@pytest.mark.issue(403)
def test_file_finder_no_history(wd, caplog):
    file_list = git_find_files(str(wd.cwd))
    assert file_list == []

    assert "listing git files failed - pretending there aren't any" in caplog.text


@pytest.mark.issue("https://github.com/pypa/setuptools_scm/issues/281")
def test_parse_call_order(wd):
    git.parse(str(wd.cwd), git.DEFAULT_DESCRIBE)


def test_version_from_git(wd):
    assert wd.version == "0.1.dev0"

    assert git.parse(str(wd.cwd), git.DEFAULT_DESCRIBE).branch in ("master", "main")

    wd.commit_testfile()
    assert wd.version.startswith("0.1.dev1+g")
    assert not wd.version.endswith("1-")

    wd("git tag v0.1")
    assert wd.version == "0.1"

    wd.write("test.txt", "test2")
    assert wd.version.startswith("0.2.dev0+g")

    wd.commit_testfile()
    assert wd.version.startswith("0.2.dev1+g")

    wd("git tag version-0.2")
    assert wd.version.startswith("0.2")

    wd.commit_testfile()
    wd("git tag version-0.2.post210+gbe48adfpost3+g0cc25f2")
    with pytest.warns(
        UserWarning, match="tag '.*' will be stripped of its suffix '.*'"
    ):
        assert wd.version.startswith("0.2")

    wd.commit_testfile()
    wd("git tag 17.33.0-rc")
    assert wd.version == "17.33.0rc0"

    # custom normalization
    assert wd.get_version(normalize=False) == "17.33.0-rc"
    assert wd.get_version(version_cls=NonNormalizedVersion) == "17.33.0-rc"
    assert (
        wd.get_version(version_cls="setuptools_scm.NonNormalizedVersion")
        == "17.33.0-rc"
    )


@pytest.mark.parametrize("with_class", [False, type, str])
def test_git_version_unnormalized_setuptools(with_class, tmpdir, wd, monkeypatch):
    """
    Test that when integrating with setuptools without normalization,
    the version is not normalized in write_to files,
    but still normalized by setuptools for the final dist metadata.
    """
    monkeypatch.delenv("SETUPTOOLS_SCM_DEBUG")
    p = wd.cwd

    # create a setup.py
    dest_file = str(tmpdir.join("VERSION.txt")).replace("\\", "/")
    if with_class is False:
        # try normalize = False
        setup_py = """
from setuptools import setup
setup(use_scm_version={'normalize': False, 'write_to': '%s'})
"""
    elif with_class is type:
        # custom non-normalizing class
        setup_py = """
from setuptools import setup

class MyVersion:
    def __init__(self, tag_str: str):
        self.version = tag_str

    def __repr__(self):
        return self.version

setup(use_scm_version={'version_cls': MyVersion, 'write_to': '%s'})
"""
    elif with_class is str:
        # non-normalizing class referenced by name
        setup_py = """from setuptools import setup
setup(use_scm_version={
    'version_cls': 'setuptools_scm.NonNormalizedVersion',
    'write_to': '%s'
})
"""

    # finally write the setup.py file
    p.joinpath("setup.py").write_text(setup_py % dest_file)

    # do git operations and tag
    wd.commit_testfile()
    wd("git tag 17.33.0-rc1")

    # setuptools still normalizes using packaging.Version (removing the dash)
    res = do((sys.executable, "setup.py", "--version"), p)
    assert res == "17.33.0rc1"

    # but the version tag in the file is non-normalized (with the dash)
    assert tmpdir.join("VERSION.txt").read() == "17.33.0-rc1"


@pytest.mark.issue(179)
def test_unicode_version_scheme(wd):
    scheme = b"guess-next-dev".decode("ascii")
    assert wd.get_version(version_scheme=scheme)


@pytest.mark.issue(108)
@pytest.mark.issue(109)
def test_git_worktree(wd):
    wd.write("test.txt", "test2")
    # untracked files dont change the state
    assert wd.version == "0.1.dev0"
    wd("git add test.txt")
    assert wd.version.startswith("0.1.dev0+d")


@pytest.mark.issue(86)
@pytest.mark.parametrize("today", [False, True])
def test_git_dirty_notag(today, wd, monkeypatch):
    if today:
        monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    wd.commit_testfile()
    wd.write("test.txt", "test2")
    wd("git add test.txt")
    assert wd.version.startswith("0.1.dev1")
    if today:
        # the date on the tag is in UTC
        tag = datetime.now(timezone.utc).date().strftime(".d%Y%m%d")
    else:
        tag = ".d20090213"
    # we are dirty, check for the tag
    assert tag in wd.version


@pytest.mark.issue(193)
@pytest.mark.xfail(reason="sometimes relative path results")
def test_git_worktree_support(wd, tmp_path):
    wd.commit_testfile()
    worktree = tmp_path / "work_tree"
    wd("git worktree add -b work-tree %s" % worktree)

    res = do([sys.executable, "-m", "setuptools_scm", "ls"], cwd=worktree)
    assert "test.txt" in res
    assert str(worktree) in res


@pytest.fixture
def shallow_wd(wd, tmpdir):
    wd.commit_testfile()
    wd.commit_testfile()
    wd.commit_testfile()
    target = tmpdir.join("wd_shallow")
    do(["git", "clone", "file://%s" % wd.cwd, str(target), "--depth=1"])
    return target


def test_git_parse_shallow_warns(shallow_wd, recwarn):
    git.parse(str(shallow_wd))
    msg = recwarn.pop()
    assert "is shallow and may cause errors" in str(msg.message)


def test_git_parse_shallow_fail(shallow_wd):
    with pytest.raises(ValueError) as einfo:
        git.parse(str(shallow_wd), pre_parse=git.fail_on_shallow)

    assert "git fetch" in str(einfo.value)


def test_git_shallow_autocorrect(shallow_wd, recwarn):
    git.parse(str(shallow_wd), pre_parse=git.fetch_on_shallow)
    msg = recwarn.pop()
    assert "git fetch was used to rectify" in str(msg.message)
    git.parse(str(shallow_wd), pre_parse=git.fail_on_shallow)


def test_find_files_stop_at_root_git(wd):
    wd.commit_testfile()
    project = wd.cwd / "project"
    project.mkdir()
    project.joinpath("setup.cfg").touch()
    assert integration.find_files(str(project)) == []


@pytest.mark.issue(128)
def test_parse_no_worktree(tmpdir):
    ret = git.parse(str(tmpdir))
    assert ret is None


def test_alphanumeric_tags_match(wd):
    wd.commit_testfile()
    wd("git tag newstyle-development-started")
    assert wd.version.startswith("0.1.dev1+g")


def test_git_archive_export_ignore(wd, monkeypatch):
    wd.write("test1.txt", "test")
    wd.write("test2.txt", "test")
    wd.write(
        ".git/info/attributes",
        # Explicitly include test1.txt so that the test is not affected by
        # a potentially global gitattributes file on the test machine.
        "/test1.txt -export-ignore\n/test2.txt export-ignore",
    )
    wd("git add test1.txt test2.txt")
    wd.commit()
    monkeypatch.chdir(wd.cwd)
    assert integration.find_files(".") == [opj(".", "test1.txt")]


@pytest.mark.issue(228)
def test_git_archive_subdirectory(wd, monkeypatch):
    os.mkdir(wd.cwd / "foobar")
    wd.write("foobar/test1.txt", "test")
    wd("git add foobar")
    wd.commit()
    monkeypatch.chdir(wd.cwd)
    assert integration.find_files(".") == [opj(".", "foobar", "test1.txt")]


@pytest.mark.issue(251)
def test_git_archive_run_from_subdirectory(wd, monkeypatch):
    os.mkdir(wd.cwd / "foobar")
    wd.write("foobar/test1.txt", "test")
    wd("git add foobar")
    wd.commit()
    monkeypatch.chdir(wd.cwd / "foobar")
    assert integration.find_files(".") == [opj(".", "test1.txt")]


def test_git_feature_branch_increments_major(wd):
    wd.commit_testfile()
    wd("git tag 1.0.0")
    wd.commit_testfile()
    assert wd.get_version(version_scheme="python-simplified-semver").startswith("1.0.1")
    wd("git checkout -b feature/fun")
    wd.commit_testfile()
    assert wd.get_version(version_scheme="python-simplified-semver").startswith("1.1.0")


@pytest.mark.issue("https://github.com/pypa/setuptools_scm/issues/303")
def test_not_matching_tags(wd):
    wd.commit_testfile()
    wd("git tag apache-arrow-0.11.1")
    wd.commit_testfile()
    wd("git tag apache-arrow-js-0.9.9")
    wd.commit_testfile()
    assert wd.get_version(
        tag_regex=r"^apache-arrow-([\.0-9]+)$",
        git_describe_command="git describe --dirty --tags --long --exclude *js* ",
    ).startswith("0.11.2")


@pytest.mark.issue("https://github.com/pypa/setuptools_scm/issues/411")
@pytest.mark.xfail(reason="https://github.com/pypa/setuptools_scm/issues/449")
def test_non_dotted_version(wd):
    wd.commit_testfile()
    wd("git tag apache-arrow-1")
    wd.commit_testfile()
    assert wd.get_version().startswith("2")


def test_non_dotted_version_with_updated_regex(wd):
    wd.commit_testfile()
    wd("git tag apache-arrow-1")
    wd.commit_testfile()
    assert wd.get_version(tag_regex=r"^apache-arrow-([\.0-9]+)$").startswith("2")


def test_non_dotted_tag_no_version_match(wd):
    wd.commit_testfile()
    wd("git tag apache-arrow-0.11.1")
    wd.commit_testfile()
    wd("git tag apache-arrow")
    wd.commit_testfile()
    assert wd.get_version().startswith("0.11.2.dev2")


@pytest.mark.issue("https://github.com/pypa/setuptools_scm/issues/381")
def test_gitdir(monkeypatch, wd):
    """ """
    wd.commit_testfile()
    normal = wd.version
    # git hooks set this and break subsequent setuptools_scm unless we clean
    monkeypatch.setenv("GIT_DIR", __file__)
    assert wd.version == normal


def test_git_getdate(wd):
    # TODO: case coverage for git wd parse
    today = date.today()

    def parse_date():
        return git.parse(os.fspath(wd.cwd)).node_date

    git_wd = git.GitWorkdir(os.fspath(wd.cwd))
    assert git_wd.get_head_date() is None
    assert parse_date() == today

    wd.commit_testfile()
    assert git_wd.get_head_date() == today
    meta = git.parse(os.fspath(wd.cwd))
    assert meta.node_date == today


def test_git_getdate_badgit(
    wd,
):
    wd.commit_testfile()
    git_wd = git.GitWorkdir(os.fspath(wd.cwd))
    with patch.object(git_wd, "do_ex", Mock(return_value=("%cI", "", 0))):
        assert git_wd.get_head_date() is None


@pytest.fixture
def signed_commit_wd(monkeypatch, wd):
    if not has_command("gpg", args=["--version"], warn=False):
        pytest.skip("gpg executable not found")

    wd.write(
        ".gpg_batch_params",
        """\
%no-protection
%transient-key
Key-Type: RSA
Key-Length: 2048
Name-Real: a test
Name-Email: test@example.com
Expire-Date: 0
""",
    )
    monkeypatch.setenv("GNUPGHOME", str(wd.cwd.resolve(strict=True)))
    wd("gpg --batch --generate-key .gpg_batch_params")

    wd("git config log.showSignature true")
    wd.signed_commit_command = "git commit -S -m test-{reason}"
    return wd


@pytest.mark.issue("https://github.com/pypa/setuptools_scm/issues/548")
def test_git_getdate_signed_commit(signed_commit_wd):
    today = date.today()
    signed_commit_wd.commit_testfile(signed=True)
    git_wd = git.GitWorkdir(os.fspath(signed_commit_wd.cwd))
    assert git_wd.get_head_date() == today
