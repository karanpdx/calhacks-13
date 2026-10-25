"""Live mode plumbing, offline: a fake live source stands in for the CRS sandbox (no network, no credentials)."""
import os

for k in ("CRS_USER", "CRS_PASS", "ANTHROPIC_API_KEY"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402

from agent.sources import FallbackSource, SampleSource  # noqa: E402
from app.main import app  # noqa: E402
from exchange.messages import Mandate  # noqa: E402
from exchange.referee import Exchange  # noqa: E402
from exchange.scenarios import build  # noqa: E402

client = TestClient(app)


class FakeLive:
    """Answers from the saved samples, except products listed in `broken` (None) or `boom` (raises)."""
    name = "live"

    def __init__(self, broken=(), boom=()):
        self.s, self.broken, self.boom, self.log = SampleSource(), set(broken), set(boom), []

    def get(self, persona, product):
        if product in self.boom:
            raise TimeoutError("vendor timeout")
        return None if product in self.broken else self.s.get(persona, product)

    def applicant(self, persona):
        return self.s.applicant(persona)


def session(src):
    lenders, borrower = build("normal")
    return Exchange("P01", Mandate(), src, lenders, borrower).run()


def test_a_failed_live_product_falls_back_to_its_sample_and_is_recorded():
    src = FallbackSource(FakeLive(broken={"efx"}, boom={"exp"}))
    r = session(src)
    assert r["deal"]                                      # the demo still works
    assert {f["product"] for f in src.fallbacks} == {"efx", "exp"}
    assert {f["why"] for f in src.fallbacks} == {"no usable response", "TimeoutError"}
    assert "vendor timeout" not in str(src.fallbacks)     # never the error text


def test_a_clean_live_run_records_no_fallbacks():
    src = FallbackSource(FakeLive())
    session(src)
    assert src.fallbacks == [] and src.name == "live"


def test_live_without_credentials_says_so_and_uses_samples():
    r = client.get("/api/exchange/P01?live=1").json()
    assert r["data_source"] == "samples" and "CRS_USER" in r["live_note"]
    assert client.get("/api/exchange/P01").json()["live_note"] is None


def test_page_passes_live_mode_through():
    html = client.get("/phone").text
    assert 'get("live") === "0" ? "" : "live=1"' in html
    assert '"/api/exchange/' in html and 'id="src"' in html
