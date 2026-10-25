"""Simulated lenders. Each has a FIXED underwriting policy (eligibility + price range) computed from the passport.

Two layers on purpose:
  - policy (here, deterministic): who they lend to and the APR range they're allowed to offer. Explainable pricing.
  - negotiation (the agent): how they move inside that range. RuleLender below is a simple stand-in;
    a Claude-powered lender should subclass it and override `respond_to_counter` only, never `policy`.
"""
from dataclasses import dataclass
from typing import Optional

from .messages import Message, Terms, OFFER, DECLINE


@dataclass
class Quote:
    eligible: bool
    reason: str
    open_apr: float = 0.0
    floor_apr: float = 0.0       # lowest APR the policy allows (without autopay)
    autopay_discount: float = 0.0
    max_amount: float = 0.0
    term: int = 36
    fee: float = 0.0


def prime_bank(p):
    if p["no_file"] or p["no_score"]:
        return Quote(False, "needs a scored credit file")
    if p["score_low"] < 700:
        return Quote(False, f"lowest score {p['score_low']} is below our 700 minimum")
    if p["late_payments"] or p["collections"] or p["chargeoffs"]:
        return Quote(False, "needs a file with no late payments, collections or charge-offs")
    if p["thin_file"]:
        return Quote(False, "needs at least 3 accounts of history")
    if p["bureau_disagreements"]:
        return Quote(False, "the bureaus disagree about this file; we only lend on consistent files")
    apr = 8.5 + max(0, (780 - p["score_low"]) / 20)
    return Quote(True, "prime file", round(apr, 2), round(apr - 2.0, 2), 0.25, 25000, 36)


def campus_cu(p):
    if p["no_file"]:
        return Quote(False, "needs at least one account on file")
    if p["collections"] or p["chargeoffs"] or p["bankruptcies"]:
        return Quote(False, "no collections, charge-offs or bankruptcies")
    if p["score_low"] is not None and p["score_low"] < 620:
        return Quote(False, f"lowest score {p['score_low']} is below our 620 minimum")
    apr = 12.5 + (1.0 if p["thin_file"] or p["no_score"] else 0) + (0.5 if p["bureau_disagreements"] else 0)
    return Quote(True, "short histories welcome", apr, 9.9, 0.5, 5000, 36)


def newstart_fintech(p):
    if p["identity"] != "strong":
        return Quote(False, "we lend on identity strength, and this identity isn't strong enough")
    if p["bankruptcies"]:
        return Quote(False, "no bankruptcies")
    if not (p["no_file"] or p["no_score"] or p["thin_file"] or (p["score_low"] or 0) >= 600):
        return Quote(False, "we focus on new-to-credit and thin files")
    return Quote(True, "new to credit, strong identity", 19.9, 15.9, 0.5, 3000, 24)


def second_chance(p):
    if p["identity"] == "weak":
        return Quote(False, "identity checks didn't pass")
    if p["no_file"] or p["score_low"] is None:
        return Quote(False, "needs a scored file")
    if p["score_low"] < 500:
        return Quote(False, f"lowest score {p['score_low']} is below our 500 minimum")
    return Quote(True, "rebuilding credit", 29.9, 24.9, 1.0, 5000, 36, fee=150)


POLICIES = {
    "prime_bank": ("Prime Bank", prime_bank),
    "campus_cu": ("Campus Credit Union", campus_cu),
    "newstart": ("NewStart Fintech", newstart_fintech),
    "second_chance": ("Second Chance Lending", second_chance),
}


class RuleLender:
    role = "lender"

    def __init__(self, agent_id):
        self.id = agent_id
        self.name, self.policy = POLICIES[agent_id]
        self.quote: Optional[Quote] = None
        self.current: Optional[Terms] = None

    def _term(self, ask):
        lo, hi = ask.get("term_range", [12, 48])
        return max(lo, min(hi, self.quote.term))

    def respond_to_intent(self, intent: Message, passport) -> Message:
        self.quote = q = self.policy(passport)
        if not q.eligible:
            return Message(DECLINE, self.id, to=intent.sender, text=f"{self.name}: {q.reason}.")
        amt = min(intent.ask["amount"], q.max_amount)
        self.current = Terms(amt, q.open_apr, self._term(intent.ask), False, q.fee)
        return Message(OFFER, self.id, to=intent.sender, terms=self.current,
                       text=f"{self.name}: {q.reason}. ${amt:,.0f} at {q.open_apr}% for {self.current.term_months} months"
                            + (f", ${q.fee:.0f} origination fee." if q.fee else "."))

    def respond_to_counter(self, counter: Message, passport, market) -> Optional[Message]:
        """market = {"best_competing_apr": float|None}. Return a new OFFER, a DECLINE, or None (stand pat)."""
        q, want = self.quote, counter.terms
        floor = q.floor_apr - (q.autopay_discount if want.autopay else 0)
        apr = round(max(want.apr, floor), 2)
        fee = self.current.fee
        if want.fee < fee:  # asked to waive the fee: we'll waive it if they take autopay
            fee = 0.0 if want.autopay else fee
        new = Terms(self.current.amount, min(apr, self.current.apr), self.current.term_months, want.autopay, fee)
        if new.key() == self.current.key():
            return Message(DECLINE, self.id, to=counter.sender, offer_id=counter.offer_id,
                           text=f"{self.name}: {self.current.apr}% is our best.")
        self.current = new
        return Message(OFFER, self.id, to=counter.sender, terms=new,
                       text=f"{self.name}: we can do {new.apr}%" + (" with autopay" if new.autopay else "")
                            + (", fee waived" if q.fee and not new.fee else "") + ".")
