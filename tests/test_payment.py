"""Monthly-payment mandates: the person sets the most they can pay each month instead of an APR.
Offline: saved samples, rule-based agents (Claude is a stub client), no network, no API key."""
import os

for k in ("CRS_USER", "CRS_PASS", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_MODEL"):
    os.environ.pop(k, None)

from agent.scorecard import AS_OF  # noqa: E402
from agent.sources import SampleSource  # noqa: E402
from exchange import demo, finance  # noqa: E402
from exchange.borrower import RuleBorrower  # noqa: E402
from exchange.llm_agents import ClaudeBorrower  # noqa: E402
from exchange.messages import Mandate, Message, Terms, ACCEPT, COUNTER, OFFER  # noqa: E402
from exchange.referee import Exchange  # noqa: E402
from exchange.scenarios import build  # noqa: E402
from test_llm_agents import OFFERS, StubClient, act, prompt  # noqa: E402  (pytest puts tests/ on sys.path)


def pay(t):
    return finance.monthly_payment(t.amount, t.apr, t.term_months)


def run(persona, borrower=None, **m):
    lenders, default_borrower = build("normal")
    return Exchange(persona, Mandate(**m), SampleSource(), lenders, borrower or default_borrower, today=AS_OF).run()


# ------------------------------------------------------------------ Mandate.allows

def test_payment_limit_rejects_terms_that_cost_too_much_each_month():
    m = Mandate(max_payment=150)
    assert m.allows(Terms(5000, 9.0, 48))[0]                  # about $124 a month
    ok, why = m.allows(Terms(5000, 9.0, 36))                  # about $159 a month, APR well inside 18%
    assert not ok and why == "monthly payment $159 above the person's limit of $150"


def test_payment_limit_is_inclusive_and_never_reads_as_150_above_150():
    t = Terms(3600, 0.0, 24)                                  # exactly $150.00
    assert Mandate(max_payment=150).allows(t)[0]
    ok, why = Mandate(max_payment=149.8).allows(t)
    assert not ok and "$150.00 above the person's limit of $149.80" in why


def test_no_payment_limit_by_default_and_apr_still_applies_with_one():
    assert Mandate().max_payment is None and Mandate().allows(Terms(5000, 9.0, 36))[0]
    ok, why = Mandate(max_payment=1000).allows(Terms(5000, 19.0, 36))
    assert not ok and "APR" in why


def test_positional_construction_still_works():
    m = Mandate(4000, 2000, 15.0, 12, 36, {"autopay"}, 0.0)
    assert (m.max_apr, m.max_fee, m.max_rounds, m.max_payment) == (15.0, 0.0, 4, None)


# ------------------------------------------------------------------ a market session

def test_payment_limit_makes_the_agent_negotiate_a_longer_loan():
    r = run("P03", max_payment=150)  # max_apr stays at the default 18%
    campus = [Terms(**e["data"]["terms"]) for e in r["events"]
              if e["kind"] == "message" and e["actor"] == "campus_cu" and e["data"]["type"] == OFFER]
    # Campus CU opens at 36 months: inside the APR limit, but more than $150 a month
    assert campus and campus[0].term_months == 36 and pay(campus[0]) > 150
    # the agent asks for a longer loan instead of settling for less money; the lender prices the restructure
    asked = [e for e in r["events"] if e["kind"] == "message" and e["data"]["type"] == "COUNTER"
             and e["data"]["to"] == "campus_cu"]
    assert asked and asked[0]["data"]["terms"]["term_months"] == 48
    deal = Terms(**r["deal"]["terms"])
    assert r["deal"]["lender"] == "campus_cu" and deal.term_months == 48 and deal.amount == 5000
    assert pay(deal) <= 150 and not r["blocked"]


def test_without_the_payment_limit_the_same_person_gets_the_bigger_loan():
    r = run("P03")
    assert r["deal"]["lender"] == "campus_cu" and pay(Terms(**r["deal"]["terms"])) > 150


# ------------------------------------------------------------------ the referee enforces it

def test_referee_blocks_an_accept_that_breaks_the_payment_limit():
    ex = Exchange("P01", Mandate(max_payment=150), SampleSource(), today=AS_OF)
    ex.gate()
    lender, borrower = ex.lenders[0], ex.borrower
    assert ex.send(lender, Message(OFFER, lender.id, terms=Terms(5000, 9, 36))).ok
    oid = next(iter(ex.offers))
    v = ex.send(borrower, Message(ACCEPT, borrower.id, offer_id=oid, terms=Terms(5000, 9, 36)))
    assert v.code == "OUTSIDE_MANDATE" and "monthly payment $159" in v.reason and ex.deal is None


class AcceptsCheapestRate(RuleBorrower):
    """A careless borrower agent: grabs the lowest APR and ignores the person's monthly limit."""

    def decide(self, rnd, offers, mandate, passport):
        oid = min(offers, key=lambda o: offers[o]["terms"].apr)
        return [Message(ACCEPT, self.id, to=offers[oid]["lender"], offer_id=oid, terms=offers[oid]["terms"])]


def test_referee_blocks_a_careless_agent_in_a_full_session():
    r = run("P01", borrower=AcceptsCheapestRate(), max_payment=150)
    blocked = [b for b in r["blocked"] if b["code"] == "OUTSIDE_MANDATE"]
    assert blocked and r["deal"] is None


# ------------------------------------------------------------------ Claude borrower keeps the limit private

def test_claude_borrower_gets_the_payment_limit_marked_private():
    stub = StubClient({"actions": [act(ACCEPT, "o1")]})
    ClaudeBorrower(client=stub).decide(0, OFFERS, Mandate(max_payment=175), {})
    p = prompt(stub.requests[0])
    assert '"max_monthly_payment_private": 175' in p and "monthly payment are private" in stub.requests[0]["system"]


def test_payment_limit_never_leaks_into_message_text():
    stub = StubClient({"actions": [act(COUNTER, "o1", apr=11.0, text="I can only afford $175 a month, so 11%?")]})
    [m] = ClaudeBorrower(client=stub).decide(0, OFFERS, Mandate(max_payment=175), {})
    assert "175" not in m.text
    safe = ClaudeBorrower._safe
    assert safe("Could you do it on $1,750 instead?", Mandate(max_payment=175)) == "Could you do it on $1,750 instead?"
    assert "175" not in safe("Budget is 175.00 tops", Mandate(max_payment=175))


# ------------------------------------------------------------------ CLI

def test_demo_cli_sets_max_payment(monkeypatch, capsys):
    seen = {}

    class FakeExchange:
        def __init__(self, persona, mandate, *a, **kw):
            seen["mandate"] = mandate

        def run(self):
            return {"events": []}

    monkeypatch.setattr(demo, "Exchange", FakeExchange)
    demo.main(["P03", "--max-payment", "150", "--json"])
    assert seen["mandate"].max_payment == 150 and seen["mandate"].max_apr == 18.0
    capsys.readouterr()
