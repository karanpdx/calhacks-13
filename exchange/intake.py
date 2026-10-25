"""Chat intake: the person talks to their agent, and the agent turns the conversation into a Mandate.

Claude proposes the fields, code decides: every number is clamped to the exchange's limits before it becomes a
Mandate, and nothing here can widen what the referee allows. Without ANTHROPIC_API_KEY (or on any model error) a
small rule-based parser reads the numbers straight from the person's own messages, so the demo and tests run offline.

The chat is stateless: the client sends the whole conversation each turn and gets back the agent's reply, the fields
understood so far, and a Mandate once the three essentials (amount, highest APR, repayment term) are known. The UI
shows that Mandate back to the person to confirm before anything goes to the market.
"""
import re

from .llm_agents import ClaudeMixin, Fallback
from .messages import Mandate, APR_CAP

LIMITS = {"amount": (100, 100000), "max_apr": (0.0, APR_CAP), "term": (3, 84), "max_fee": (0, 5000)}
QUESTIONS = {
    "amount": "How much do you want to borrow, and what's it for?",
    "max_apr": "What's the highest APR you'd accept? I'll never agree to anything above it.",
    "term": "Over how many months would you like to pay it back?",
}
MAX_TURNS, MAX_CHARS = 40, 2000

NULLABLE_NUM = {"anyOf": [{"type": "number"}, {"type": "null"}]}
NULLABLE_INT = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
NULLABLE_BOOL = {"anyOf": [{"type": "boolean"}, {"type": "null"}]}
NULLABLE_STR = {"anyOf": [{"type": "string"}, {"type": "null"}]}
FIELD_SCHEMA = {"amount": NULLABLE_NUM, "min_amount": NULLABLE_NUM, "max_apr": NULLABLE_NUM, "min_term": NULLABLE_INT,
                "max_term": NULLABLE_INT, "autopay": NULLABLE_BOOL, "max_fee": NULLABLE_NUM, "purpose": NULLABLE_STR}
SCHEMA = {
    "type": "object",
    "properties": {"reply": {"type": "string"}, **FIELD_SCHEMA},
    "required": ["reply", *FIELD_SCHEMA],
    "additionalProperties": False,
}

SYSTEM = ("You are a person's credit agent on a credit exchange. Before you shop for a loan you need their limits: "
          "how much to borrow (and the least they'd take), the highest APR they'd accept, the repayment term in "
          "months (a range is fine), whether they'd agree to autopay for a lower rate, and the most they'd pay in "
          "fees. Read the conversation and fill in only what the person actually said; use null for anything they "
          "haven't said, and never invent numbers. Convert years to months. 'No fees' means max_fee 0. Then write "
          "a short, friendly reply: confirm what you understood and ask for the next missing essential (amount, "
          "highest APR, term), one question at a time. When the essentials are known, summarise the limits and "
          "ask them to confirm. Never promise a rate, an approval, or a lender.")


def clean(fields):
    """Clamp model or parser output into safe values. Unknown or nonsensical values become None."""
    def num(x, lo, hi):
        if isinstance(x, bool) or not isinstance(x, (int, float)) or x != x:
            return None
        return min(max(float(x), lo), hi)

    f = {k: fields.get(k) for k in FIELD_SCHEMA}
    out = {"amount": num(f["amount"], *LIMITS["amount"]) if (f["amount"] or 0) > 0 else None,
           "max_apr": num(f["max_apr"], *LIMITS["max_apr"]),
           "max_fee": num(f["max_fee"], *LIMITS["max_fee"]),
           "autopay": f["autopay"] if isinstance(f["autopay"], bool) else None,
           "purpose": str(f["purpose"])[:80] if f["purpose"] else None}
    terms = [int(num(t, *LIMITS["term"])) for t in (f["min_term"], f["max_term"]) if num(t, *LIMITS["term"]) is not None]
    out["min_term"], out["max_term"] = (min(terms), max(terms)) if terms else (None, None)
    lo = num(f["min_amount"], *LIMITS["amount"]) if (f["min_amount"] or 0) > 0 else None
    out["min_amount"] = min(lo, out["amount"]) if lo is not None and out["amount"] else None
    return out


def missing(fields):
    need = [k for k in ("amount", "max_apr") if fields.get(k) is None]
    if fields.get("max_term") is None:
        need.append("term")
    return need


def to_mandate(fields):
    """A Mandate from cleaned fields, or None while an essential is missing. Defaults are the conservative ones:
    no fees and no autopay unless the person said so."""
    if missing(fields):
        return None
    amount, max_term = fields["amount"], fields["max_term"]
    min_term = fields["min_term"] if fields["min_term"] is not None and fields["min_term"] < max_term else min(12, max_term)
    return Mandate(amount=amount, min_amount=fields["min_amount"] or round(amount * 0.6, -2) or amount,
                   max_apr=fields["max_apr"], min_term=min_term, max_term=max_term,
                   allow={"autopay"} if fields["autopay"] else set(), max_fee=fields["max_fee"] or 0.0)


def mandate_dict(m):
    return {**vars(m), "allow": sorted(m.allow)} if m else None


# ---------------------------------------------------------------- rule-based fallback (no API key, or model error)

def _money(s):
    m = re.fullmatch(r"\$?\s*([\d,]+(?:\.\d+)?)\s*(k)?", s.strip(), re.I)
    return float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1) if m else None


def parse(user_texts):
    """Pull the limits out of the person's own messages with regexes. Later messages override earlier ones."""
    f = {}
    for t in user_texts:
        low = t.lower()
        if re.search(r"\b(no|zero|without)\s+(origination\s+)?fees?\b|\$0\s+fee", low):
            f["max_fee"] = 0
        fee = re.search(r"fees?\s+(?:of\s+|up\s+to\s+|under\s+)?(\$\s?[\d,]+(?:\.\d+)?k?)|(\$\s?[\d,]+(?:\.\d+)?k?)\s+(?:origination\s+)?fee", low)
        if fee:
            f["max_fee"] = _money(fee.group(1) or fee.group(2))
        amounts = [a for a in re.findall(r"\$\s?[\d,]+(?:\.\d+)?k?|\b\d+(?:\.\d+)?k\b", low)
                   if not fee or a not in fee.group(0)]
        amounts = [v for v in map(_money, amounts) if v]
        if amounts:
            f["amount"] = max(amounts)
            if len(amounts) > 1:
                f["min_amount"] = min(amounts)
        apr = re.findall(r"(\d+(?:\.\d+)?)\s*%", low)
        if apr:
            f["max_apr"] = float(apr[-1])
        rng = re.search(r"(\d+)\s*(?:-|to|and)\s*(\d+)\s*(months?|mos?|years?|yrs?)\b", low)
        one = re.findall(r"(\d+)\s*-?\s*(months?|mos?|years?|yrs?)\b", low)
        if rng:
            k = 12 if rng.group(3).startswith("y") else 1
            f["min_term"], f["max_term"] = int(rng.group(1)) * k, int(rng.group(2)) * k
        elif one:
            n, unit = one[-1]
            f["max_term"] = int(n) * (12 if unit.startswith("y") else 1)
            f.pop("min_term", None)
        if "autopay" in low or "auto-pay" in low or "auto pay" in low:
            f["autopay"] = not re.search(r"\b(no|not|don't|dont|without|never)\b[^.]{0,20}auto[- ]?pay", low)
    return f


def rule_reply(fields):
    need = missing(fields)
    if need:
        return QUESTIONS[need[0]]
    m = to_mandate(fields)
    return (f"Got it: up to ${m.amount:,.0f} (at least ${m.min_amount:,.0f}), no more than {m.max_apr:g}% APR, "
            f"{m.min_term}-{m.max_term} months, " + ("autopay OK, " if "autopay" in m.allow else "no autopay, ")
            + (f"fees up to ${m.max_fee:,.0f}." if m.max_fee else "no fees.") + " Shall I take this to the market?")


# ---------------------------------------------------------------- the agent

class MandateChat(ClaudeMixin):
    id = "intake"

    def __init__(self, client=None):
        self._setup_claude(client)

    def turn(self, messages):
        """messages = [{"role": "user"|"agent", "content": str}, ...], oldest first. Returns the agent's next turn."""
        msgs = [{"role": "user" if m.get("role") == "user" else "agent", "content": str(m.get("content", ""))[:MAX_CHARS]}
                for m in messages[-MAX_TURNS:]]
        try:
            raw = self._claude(msgs)
            fields, reply, source = clean(raw), raw["reply"].strip(), "claude"
            if not reply:
                raise Fallback("empty reply")
            self.last_source = "claude"
        except Exception as e:  # no key, API error, refusal, bad JSON: the person still gets an answer
            self._fell_back(e)
            fields = clean(parse([m["content"] for m in msgs if m["role"] == "user"]))
            reply, source = rule_reply(fields), "rules"
        m = to_mandate(fields)
        return {"reply": reply, "fields": fields, "missing": missing(fields), "ready": m is not None,
                "mandate": mandate_dict(m), "source": source}

    def _claude(self, msgs):
        if not any(m["role"] == "user" for m in msgs):
            raise Fallback("nothing from the person yet")
        convo = "\n".join(f"{'Person' if m['role'] == 'user' else 'You (agent)'}: {m['content']}" for m in msgs)
        return self.ask(SYSTEM, "Conversation so far:\n" + convo + "\n\nReturn the fields and your reply as JSON.", SCHEMA)
