"""The .env loader: real env wins, quotes and comments handled, and it never runs under pytest."""
import os

from agent import envfile


def test_skipped_under_pytest(tmp_path):
    f = tmp_path / ".env"
    f.write_text("ENVFILE_TEST_A=1\n")
    assert envfile.load(str(f)) == [] and "ENVFILE_TEST_A" not in os.environ


def test_parses_lines_when_not_under_pytest(tmp_path, monkeypatch):
    import sys
    f = tmp_path / ".env"
    f.write_text("# comment\nexport ENVFILE_TEST_B='quoted value'\nENVFILE_TEST_C=plain # note\nENVFILE_TEST_D=\n"
                 "ENVFILE_TEST_E=keep-real\n")
    monkeypatch.setenv("ENVFILE_TEST_E", "real")
    saved = sys.modules.pop("pytest")
    try:
        names = envfile.load(str(f))
    finally:
        sys.modules["pytest"] = saved
        for k in ("ENVFILE_TEST_B", "ENVFILE_TEST_C"):
            got = os.environ.pop(k, None)
            if k == "ENVFILE_TEST_B":
                assert got == "quoted value"
            else:
                assert got == "plain"
    assert set(names) == {"ENVFILE_TEST_B", "ENVFILE_TEST_C"} and os.environ["ENVFILE_TEST_E"] == "real"
