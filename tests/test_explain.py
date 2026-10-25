from agent.explain import explain
from agent.scorecard import AS_OF, EXPECTED
from agent.screen import screen
from agent.sources import SampleSource


def test_every_persona_gets_short_text_with_caveat():
    for p in EXPECTED:
        e = explain(screen(SampleSource(), p, "full", explain=False, as_of=AS_OF))
        assert 80 < len(e["text"]) < 900, (p, e["text"])
        assert "could be wrong" in e["text"] or "demo policy" in e["text"]
        assert e["by"] == "template"


def test_claude_backend_needs_both_env_vars(monkeypatch):
    monkeypatch.setenv("EXPLAIN_BACKEND", "claude")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = screen(SampleSource(), "P13", "full", explain=False, as_of=AS_OF)
    assert explain(r)["by"] == "template"  # no key: never calls the API
