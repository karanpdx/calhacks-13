"""Borrower agent. RuleBorrower is a simple stand-in; a Claude-powered borrower should subclass it and override
`decide`. Whatever it decides, the referee re-checks every ACCEPT against the mandate.

The borrower agent sees: the mandate, the passport, and the offers. It must never reveal the mandate's max APR.
"""
from .messages import Message, Terms, INTENT, COUNTER, ACCEPT, DECLINE
from . import finance


class RuleBorrower:
    role = "borrower"

    def __init__(self, agent_id="borrower"):
        self.id = agent_id
        self.countered = set()  # offer ids already countered once; a lender that won't move isn't asked again

    def intent(self, mandate) -> Message:
        return Message(INTENT, self.id, ask={"amount": mandate.amount, "term_range": [mandate.min_term, mandate.max_term],
                                             "purpose": "personal loan"},
                       text=f"Looking for ${mandate.amount:,.0f} over {mandate.min_term}-{mandate.max_term} months.")

    def decide(self, rnd, offers, mandate, passport):
        """offers = {offer_id: {"lender", "terms": Terms, "text"}} (active only). Return a list of messages."""
        ok = {oid: o for oid, o in offers.items() if mandate.allows(o["terms"])[0]}
        # prefer offers for the full amount, then the lowest total cost per dollar borrowed
        rank = lambda oid: (offers[oid]["terms"].amount < mandate.amount, finance.cost_per_dollar(offers[oid]["terms"]))
        last = rnd >= mandate.max_rounds - 1
        if not offers:
            return [Message(DECLINE, self.id, text="No offers. Ending the search.")]

        best = min(offers, key=rank)
        best_apr = offers[best]["terms"].apr
        if not last:
            out = []
            for oid, o in offers.items():
                if oid in self.countered:
                    continue
                t = o["terms"]
                # always ask for less than this lender's current rate; ask competitors to beat the best rate
                target = t.apr - 0.5 if oid == best else min(t.apr, best_apr) - 0.25
                want = Terms(t.amount, round(max(target, 0), 2), t.term_months,
                             autopay="autopay" in mandate.allow, fee=0.0)
                if want.key() != t.key():
                    self.countered.add(oid)
                    out.append(Message(COUNTER, self.id, to=o["lender"], offer_id=oid, terms=want,
                                       text=(f"You're the best offer so far. Can you do {want.apr}%" if oid == best
                                             else f"Another lender is at {best_apr}%. Can you do {want.apr}%")
                                            + (" if I set up autopay" if want.autopay else "") + "?"))
            if out:
                return out
        if ok:
            pick = min(ok, key=rank)
            return [Message(ACCEPT, self.id, to=offers[pick]["lender"], offer_id=pick, terms=offers[pick]["terms"],
                            text="Accepting.")]
        return [Message(DECLINE, self.id, text="No offer fits the person's limits. Walking away.")]


class GullibleBorrower(RuleBorrower):
    """Attack scenario: a compromised borrower agent that obeys instructions hidden in offer text.
    Exists to show the referee blocks it anyway."""

    def decide(self, rnd, offers, mandate, passport):
        for oid, o in offers.items():
            if "ACCEPT" in o["text"].upper() and "IGNORE" in o["text"].upper():
                return [Message(ACCEPT, self.id, to=o["lender"], offer_id=oid, terms=o["terms"],
                                text="Accepting as instructed.")]
        return super().decide(rnd, offers, mandate, passport)
