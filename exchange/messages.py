"""The exchange's message protocol. Every agent talks ONLY through these types; the referee validates each one.

Contract for teammates: agents may put anything in `text` (it's shown in the UI and read by the watchdog), but the
referee never acts on `text`. Only the structured fields (`type`, `terms`, `offer_id`, ...) have any effect.
"""
from dataclasses import dataclass, field, asdict
from typing import Optional
import hashlib, hmac, json, time, uuid

from .finance import monthly_payment  # finance.py imports nothing, so no cycle

# message types
INTENT = "INTENT"      # borrower -> market: what they want (no personal data)
OFFER = "OFFER"        # lender -> borrower: binding terms until expiry or withdrawal
COUNTER = "COUNTER"    # borrower -> one lender: "can you do these terms?" (references an offer)
ACCEPT = "ACCEPT"      # borrower -> one lender: take an offer exactly as made
DECLINE = "DECLINE"    # either side: no deal
WITHDRAW = "WITHDRAW"  # lender: pull its offer (allowed only before acceptance)
TYPES = {INTENT, OFFER, COUNTER, ACCEPT, DECLINE, WITHDRAW}

CONCESSIONS = {"autopay"}  # things a borrower may agree to in exchange for a lower rate
APR_CAP = 36.0             # common state-law ceiling for consumer installment loans; hard limit in the exchange


@dataclass
class Terms:
    amount: float          # dollars
    apr: float             # percent, e.g. 11.5
    term_months: int
    autopay: bool = False  # borrower agrees to autopay
    fee: float = 0.0       # origination fee in dollars; must be declared up front

    def key(self):
        return (round(self.amount, 2), round(self.apr, 3), self.term_months, self.autopay, round(self.fee, 2))


@dataclass
class Mandate:
    """What the person authorises their agent to do. The agent can never accept outside this.

    `max_payment` (dollars per month) is the plain-words limit for people who don't think in APR; when set, terms
    whose monthly payment is above it are outside the mandate. `max_apr` always applies too (an "advanced" limit)."""
    amount: float = 5000
    min_amount: float = 3000
    max_apr: float = 18.0
    min_term: int = 12
    max_term: int = 48
    allow: set = field(default_factory=lambda: {"autopay"})
    max_fee: float = 0.0
    max_rounds: int = 4
    max_payment: Optional[float] = None

    def allows(self, t: Terms):
        """Return (ok, reason)."""
        if not (self.min_amount <= t.amount <= self.amount):
            return False, f"amount ${t.amount:,.0f} outside ${self.min_amount:,.0f}-${self.amount:,.0f}"
        if t.apr > self.max_apr:
            return False, f"APR {t.apr}% above the person's limit of {self.max_apr}%"
        if not (self.min_term <= t.term_months <= self.max_term):
            return False, f"{t.term_months}-month term outside {self.min_term}-{self.max_term} months"
        if self.max_payment is not None:
            pay = monthly_payment(t.amount, t.apr, t.term_months)
            if pay > self.max_payment + 0.005:  # cents: a $150.00 payment fits a $150 limit
                fmt = ",.0f" if round(pay) != round(self.max_payment) else ",.2f"  # never "$150 above $150"
                return False, f"monthly payment ${pay:{fmt}} above the person's limit of ${self.max_payment:{fmt}}"
        if t.autopay and "autopay" not in self.allow:
            return False, "requires autopay, which the person did not allow"
        if t.fee > self.max_fee:
            return False, f"${t.fee:,.0f} fee above the person's limit of ${self.max_fee:,.0f}"
        return True, "within mandate"


@dataclass
class Message:
    type: str
    sender: str                       # agent id, e.g. "borrower", "prime_bank"
    to: Optional[str] = None          # None = whole market
    terms: Optional[Terms] = None
    offer_id: Optional[str] = None    # for OFFER: assigned by referee; for COUNTER/ACCEPT/WITHDRAW: the offer referred to
    ask: Optional[dict] = None        # INTENT only: {"amount", "term_range", "purpose"}; never the person's max APR
    cite: Optional[str] = None        # COUNTER only: a rival's live offer id the borrower shows as proof of a better
                                      # deal. The referee verifies it and passes the lender only its terms, never its source
    text: str = ""                    # free text: UNTRUSTED, never acted on by the referee
    round: int = 0
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    ts: float = field(default_factory=time.time)
    sig: str = ""

    def payload(self):
        d = asdict(self)
        d.pop("sig", None)
        return json.dumps(d, sort_keys=True, default=str).encode()

    def sign(self, key: bytes):
        self.sig = hmac.new(key, self.payload(), hashlib.sha256).hexdigest()
        return self

    def verify(self, key: bytes):
        return hmac.compare_digest(self.sig, hmac.new(key, self.payload(), hashlib.sha256).hexdigest())

    def to_dict(self):
        d = asdict(self)
        d.pop("sig", None)
        return d


@dataclass
class Verdict:
    ok: bool
    code: str      # e.g. "OK", "OUTSIDE_MANDATE", "TERMS_CHANGED", "BAD_SIGNATURE"
    reason: str
