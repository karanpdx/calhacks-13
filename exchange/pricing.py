"""Lender economics: how a lender decides what a loan must earn, from the same building blocks banks use.

Risk-based pricing (the standard build-up a lender's pricing desk uses):

    required APR = cost of funds            what the lender pays for the money it lends
                 + expected loss            probability of default x loss given default
                 + servicing cost           running the account each year
                 + origination cost         a fixed cost per loan, spread over the loan (why small loans cost more)
                 + capital charge           capital held against the loan x the return shareholders require
                 - origination fee          a fee the borrower pays up front offsets the fixed cost

The break-even rate is that sum. A lender's FLOOR is break-even plus the smallest margin it will accept, which
depends on its private motives (how far behind its volume target it is, how full its risk bucket is). Its OPENING
rate adds a target margin on top. So the room to negotiate comes out of each lender's own books and each borrower's
risk, not from a fixed rule like "two points under the opening rate".

Probability of default comes from a log-odds scorecard, the classic credit-scoring form: odds of repaying double every
fixed number of score points ("points to double the odds"). The score already reflects late payments and
collections, so adjustments are only for what a score misses: thin files, no score at all, bureaus that disagree,
how strong the identity evidence is.

Autopay lowers missed payments and servicing cost, so its discount is computed, not fixed.

All parameter values are ILLUSTRATIVE assumptions chosen to be plausible, not calibrated to real portfolios.
"""
from dataclasses import dataclass, field

AVG_BALANCE = 0.55          # an amortizing loan's average outstanding balance, as a share of the amount
AUTOPAY_PD = 0.85           # autopay borrowers default less often (fewer missed payments)
AUTOPAY_SERVICING = 0.25    # percentage points a year saved in collections and payment handling
TERM_PREMIUM = 0.15         # funding/rate risk per extra year beyond the first, percentage points


@dataclass
class Book:
    """One lender's private economics and motives. Never shared with other agents."""
    cost_of_funds: float        # % a year
    servicing: float            # % a year of the balance
    origination_cost: float     # $ per loan
    lgd: float                  # loss given default, share of the balance lost (unsecured: most of it)
    capital_ratio: float        # capital held per $ lent
    roe_hurdle: float           # return required on that capital
    target_margin: float        # % a year above break-even when opening
    min_margin: float           # % a year: the least it accepts before motives
    volume_target: int          # loans it wants to book this month
    booked: int                 # loans booked so far this month
    month_progress: float       # share of the month gone (0-1)
    risk_bucket_fill: float     # share of its appetite for this kind of borrower already used (0-1)
    terms: tuple = (12, 24, 36)  # loan lengths it offers, months
    preferred_term: int = 36
    max_amount: float = 5000
    fee: float = 0.0            # origination fee it charges by default, $
    motive: str = ""            # one line of why it behaves as it does (shown to judges after the session)

    @property
    def volume_pressure(self):
        """0 = on or ahead of target, 1 = far behind. Behind target -> thinner margins, faster concessions."""
        expected = self.volume_target * self.month_progress
        if expected <= 0:
            return 0.0
        return max(0.0, min(1.0, (expected - self.booked) / expected))

    @property
    def concession_beta(self):
        """Time-dependent concession tactic (Faratin et al.): <1 holds firm until late, >1 concedes early."""
        return round(0.5 + 2.5 * self.volume_pressure, 2)

    @property
    def effective_min_margin(self):
        """Pressure to book loans lowers the margin it will accept; a nearly full risk bucket raises it."""
        return round(max(0.0, self.min_margin * (1 - self.volume_pressure) + 1.5 * max(0.0, self.risk_bucket_fill - 0.8)), 3)


# ---------------------------------------------------------------- probability of default (scorecard)
BASE_ODDS = 50.0       # odds of repaying : defaulting at a 700 score
BASE_SCORE = 700
PDO = 50               # points to double the odds


# Positive evidence (odds multipliers, applied only where the score says little: thin, no-score and no-file
# passports; a full scored file already reflects its payment history, so rewarding it again would double count).
NEVER_LATE_ODDS = 1.15      # no late month, charge-off or late count on any account
ON_TIME_ODDS = 1.10         # 12+ months in a row paid as agreed on some account
ON_TIME_MONTHS = 12
STABLE_ODDS = 1.05          # each of: address tied to the name, phone the applicant's own (approximations, see passport)


def positive_evidence(p):
    """[(reason, odds multiplier)] for what a thin or missing file has going for it."""
    if not (p.get("no_file") or p.get("no_score") or p.get("thin_file")):
        return []
    out = []
    if p.get("never_late"):
        out.append(("never late on any account", NEVER_LATE_ODDS))
    if (p.get("months_on_time") or 0) >= ON_TIME_MONTHS:
        out.append((f"{p['months_on_time']} months in a row paid on time", ON_TIME_ODDS))
    if p.get("address_stable"):
        out.append(("address tied to the applicant", STABLE_ODDS))
    if p.get("phone_stable"):
        out.append(("phone is the applicant's own", STABLE_ODDS))
    return out


def pd_annual(p):
    """Annual probability of default from the passport. Returns (pd, list of what moved it)."""
    why = []
    if p.get("no_file"):
        pd = {"strong": 0.06, "ok": 0.09}.get(p.get("identity"), 0.15)
        why.append(f"no credit file: {pd:.0%} prior from identity strength alone")
        odds = (1 - pd) / pd
        for text, f in positive_evidence(p):
            odds *= f
            why.append(text)
        return 1 / (1 + odds), why
    if p.get("no_score") or p.get("score_low") is None:
        pd = 0.05 if (p.get("file_age_years") or 0) >= 10 else 0.08
        why.append(f"file but no score: {pd:.0%} prior from file age")
        odds = (1 - pd) / pd
    else:
        s = p["score_low"]
        odds = BASE_ODDS * 2 ** ((s - BASE_SCORE) / PDO)
        why.append(f"score {s}: odds {odds:.0f}:1 on the scorecard")
    adj = []
    if p.get("thin_file"):
        adj.append(("thin file: less evidence either way", 1.4))
    if p.get("bureau_disagreements"):
        adj.append(("bureaus disagree", 1.15))
    if (p.get("serious_lates_90d") or 0) > 0:
        adj.append(("a 90-day late on file", 1.15))
    if (p.get("collections") or 0) > 0:
        adj.append(("collections on file", 1.1))
    if (p.get("inquiries_6m") or 0) >= 4:
        adj.append(("many recent applications", 1.2))
    if p.get("identity") == "ok":
        adj.append(("identity evidence only fair", 1.2))
    elif p.get("identity") == "weak":
        adj.append(("weak identity evidence", 2.0))
    if (p.get("file_age_years") or 0) >= 10 and not p.get("no_score"):
        adj.append(("long, seasoned file", 1 / 1.2))
    for text, f in adj:
        odds /= f
        why.append(text)
    for text, f in positive_evidence(p):
        odds *= f
        why.append(text)
    pd = 1 / (1 + odds)
    return min(0.40, max(0.003, pd)), why


# ---------------------------------------------------------------- loan economics
def breakdown(book, passport, amount, term_months, autopay=False, fee=None):
    """Annual percentage-point build-up of the break-even APR for these loan terms."""
    fee = book.fee if fee is None else fee
    pd, why = pd_annual(passport)
    if autopay:
        pd *= AUTOPAY_PD
    years = term_months / 12
    exposure = amount * AVG_BALANCE * years           # $-years of money lent out
    parts = {
        "cost_of_funds": book.cost_of_funds + TERM_PREMIUM * max(0.0, years - 1),
        "expected_loss": pd * book.lgd * 100,
        "servicing": book.servicing - (AUTOPAY_SERVICING if autopay else 0.0),
        "origination": (book.origination_cost - fee) / exposure * 100,
        "capital": book.capital_ratio * book.roe_hurdle * 100,
    }
    return {k: round(v, 3) for k, v in parts.items()}, pd, why


def break_even(book, passport, amount, term_months, autopay=False, fee=None):
    parts, _, _ = breakdown(book, passport, amount, term_months, autopay, fee)
    return round(sum(parts.values()), 2)


def floor(book, passport, amount, term_months, autopay=False, fee=None):
    """The lowest APR this lender will accept for these exact terms."""
    return round(break_even(book, passport, amount, term_months, autopay, fee) + book.effective_min_margin, 2)


def opening(book, passport, amount, term_months, fee=None):
    return round(break_even(book, passport, amount, term_months, False, fee) + book.target_margin, 2)


def concession_target(book, open_apr, floor_apr, rnd, max_rounds):
    """Where the lender is willing to be in this round: from its opening rate toward its floor, at a speed set by
    its motives. rnd counts from 1."""
    t = min(1.0, rnd / max(1, max_rounds))
    share = t ** (1 / book.concession_beta)       # share of the room given up by now
    return round(floor_apr + (open_apr - floor_apr) * (1 - share), 2)


def private_view(book, passport, amount, term_months, autopay=False, fee=None, opened=None):
    """What a lender knows about itself, for the judges' after-session view, for its final loan terms.
    Never given to other agents."""
    parts, pd, why = breakdown(book, passport, amount, term_months, autopay, fee)
    return {
        "loan": {"amount": amount, "term_months": term_months, "autopay": autopay,
                 "fee": book.fee if fee is None else fee},
        "probability_of_default": round(pd, 4), "pd_reasons": why, "break_even_build_up": parts,
        "break_even_apr": round(sum(parts.values()), 2),
        "floor_apr": floor(book, passport, amount, term_months, autopay, fee),
        "opening_apr": opened if opened is not None else opening(book, passport, amount, term_months),
        "volume_pressure": round(book.volume_pressure, 2), "concession_style":
            "concedes early" if book.concession_beta > 1.2 else "holds firm" if book.concession_beta < 0.9 else "steady",
        "motive": book.motive,
    }
