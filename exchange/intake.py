"""Chat intake: the person talks to their agent, and the agent turns the conversation into a Mandate.

Claude proposes the fields, code decides: every number is clamped to the exchange's limits before it becomes a
Mandate, and nothing here can widen what the referee allows. Without ANTHROPIC_API_KEY (or on any model error) a
small rule-based parser reads the numbers straight from the person's own messages, so the demo and tests run offline.

The chat is stateless: the client sends the whole conversation each turn and gets back the agent's reply, the fields
understood so far, and a Mandate once the three essentials are known: the amount, the repayment term, and a price
limit. The price limit is asked in plain words, the most they could pay each month, because many first-time borrowers
(students, newcomers, retirees) don't think in APR; an APR limit still works if the person brings one up. The UI
shows that Mandate back to the person to confirm before anything goes to the market.
"""
import re
import unicodedata

from .llm_agents import ClaudeMixin, Fallback
from .messages import Mandate, APR_CAP
from .i18n import language, t, money, number

LIMITS = {"amount": (100, 100000), "max_apr": (0.0, APR_CAP), "term": (3, 84), "max_fee": (0, 5000),
          "max_payment": (10, 10000)}
QUESTIONS = {  # keyed by the names missing() returns
    "amount": "How much do you want to borrow, and what's it for?",
    "payment": "What's the most you could pay each month? I'll never agree to a loan that costs more than that.",
    "term": "Over how many months would you like to pay it back?",
}
MAX_TURNS, MAX_CHARS = 40, 2000

NULLABLE_NUM = {"anyOf": [{"type": "number"}, {"type": "null"}]}
NULLABLE_INT = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
NULLABLE_BOOL = {"anyOf": [{"type": "boolean"}, {"type": "null"}]}
NULLABLE_STR = {"anyOf": [{"type": "string"}, {"type": "null"}]}
FIELD_SCHEMA = {"amount": NULLABLE_NUM, "min_amount": NULLABLE_NUM, "max_payment": NULLABLE_NUM, "max_apr": NULLABLE_NUM,
                "min_term": NULLABLE_INT, "max_term": NULLABLE_INT, "autopay": NULLABLE_BOOL, "max_fee": NULLABLE_NUM,
                "purpose": NULLABLE_STR}
SCHEMA = {
    "type": "object",
    "properties": {"reply": {"type": "string"}, **FIELD_SCHEMA},
    "required": ["reply", *FIELD_SCHEMA],
    "additionalProperties": False,
}

SYSTEM = ("You are a person's credit agent on a credit exchange. Many of the people you help are borrowing for the "
          "first time (students, newcomers to the country, retirees), so talk in plain everyday words and never use "
          "jargon. Before you shop for a loan you need their limits: how much to borrow (and the least they'd "
          "take), the most they could pay each month (max_payment, in dollars), how many months to pay it back (a "
          "range is fine), whether they'd agree to automatic payments (autopay) for a lower rate, and the most "
          "they'd pay in up-front fees. Ask about the monthly payment, not the interest rate. Only fill max_apr if "
          "the person brings up an interest rate or APR themselves; if they give both, keep both. Read the "
          "conversation and fill in only what the person actually said; use null for anything they haven't said, "
          "and never invent numbers. Convert years to months. A dollar figure 'a month', 'per month' or 'monthly' "
          "is max_payment, not the loan amount. 'No fees' means max_fee 0. Then write a short, friendly reply: "
          "confirm what you understood and ask for the next missing essential (amount, monthly payment, months), "
          "one question at a time. When the essentials are known, summarise the limits, monthly payment first, "
          "and ask them to confirm. Never promise a rate, an approval, or a lender.")


def clean(fields):
    """Clamp model or parser output into safe values. Unknown or nonsensical values become None."""
    def num(x, lo, hi):
        if isinstance(x, bool) or not isinstance(x, (int, float)) or x != x:
            return None
        return min(max(float(x), lo), hi)

    f = {k: fields.get(k) for k in FIELD_SCHEMA}
    pay = num(f["max_payment"], float("-inf"), float("inf"))  # zero or negative means "not given", not "the minimum"
    out = {"amount": num(f["amount"], *LIMITS["amount"]) if (f["amount"] or 0) > 0 else None,
           "max_payment": num(pay, *LIMITS["max_payment"]) if pay and pay > 0 else None,
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
    """Essentials still unknown, in the order the agent asks for them: "amount", "payment" (a monthly payment limit,
    or an APR limit if the person gave one instead), "term"."""
    need = ["amount"] if fields.get("amount") is None else []
    if fields.get("max_payment") is None and fields.get("max_apr") is None:
        need.append("payment")
    if fields.get("max_term") is None:
        need.append("term")
    return need


def to_mandate(fields):
    """A Mandate from cleaned fields, or None while an essential is missing. Defaults are the conservative ones:
    no fees and no autopay unless the person said so. With only a monthly payment given, the APR limit is the
    exchange's legal cap, so the payment is the binding limit; an APR the person gave applies as well."""
    if missing(fields):
        return None
    amount, max_term = fields["amount"], fields["max_term"]
    min_term = fields["min_term"] if fields["min_term"] is not None and fields["min_term"] < max_term else min(12, max_term)
    max_apr = fields["max_apr"] if fields.get("max_apr") is not None else APR_CAP
    return Mandate(amount=amount, min_amount=fields["min_amount"] or round(amount * 0.6, -2) or amount,
                   max_apr=max_apr, min_term=min_term, max_term=max_term,
                   allow={"autopay"} if fields["autopay"] else set(), max_fee=fields["max_fee"] or 0.0,
                   max_payment=fields.get("max_payment"))


def mandate_dict(m):
    return {**vars(m), "allow": sorted(m.allow)} if m else None


# ---------------------------------------------------------------- rule-based fallback (no API key, or model error)

def _money(s):
    m = re.fullmatch(r"\$?\s*([\d,]+(?:\.\d+)?)\s*(k)?", s.strip(), re.I)
    return float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1) if m else None


_NUM = r"\$?\s?\d[\d,]*(?:\.\d+)?k?"
# "$150 a month", "150/month", "150 per month", "$150/mo", "$150 monthly" (but not "12 monthly payments")
PAY_AFTER = re.compile(r"(\$\s?\d[\d,]*(?:\.\d+)?k?|\b\d[\d,]*(?:\.\d+)?k?)\s*(?:/\s*(?:months?|mo)\b|"
                       r"(?:a|per|each|every)\s+(?:month|mo)\b|monthly\b(?!\s+(?:payments|installments)\b))")
# "monthly payment of $150", "monthly payments under 200" (a whole number, not a rate or a number of months)
PAY_BEFORE = re.compile(r"monthly\s+(?:payments?\s+)?(?:(?:of|under|below|around|about|max(?:imum)?|at\s+most|up\s+to|"
                        r"no\s+more\s+than|less\s+than|is|=|:)\s*)*(" + _NUM + r")"
                        r"(?![\d,.]*\d)(?!\s*(?:%|months?\b|mos?\b|years?\b|yrs?\b))")


def _spanish_text(text):
    """Normalize Spanish phrasing into the existing parser's units, not new limits."""
    low = ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if not unicodedata.combining(c))
    if not re.search(r'\b(necesito|dolares?|mes(?:es)?|anos?|pagar|pago|pagos|comision(?:es)?|cargos?|prestamo|mil|gano|ingresos?|sueldo|alquiler)\b', low):
        return text
    # Spanish thousands/decimal punctuation, also accepting US dollar notation.
    def digits(m):
        value = m.group()
        if re.fullmatch(r'\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?', value):
            return value.replace('.', '').replace(',', '.')
        if ',' in value and not re.fullmatch(r'\d{1,3}(?:,\d{3})+', value):
            return value.replace(',', '.')
        return value
    low = re.sub(r'\d+(?:[.,]\d+)*', digits, low)
    low = re.sub(r'(\d+(?:\.\d+)?)\s+mil\b', lambda m: str(float(m[1]) * 1000), low)
    low = re.sub(r'\b(\d[\d,.]*)\s*(?:dolares?|usd)\b', r'$\1', low)
    low = re.sub(r'\b(?:gano|ingresos?|sueldo|alquiler)\s*(?:de|son|es)?\s*\$?[\d,.]+\s*(?:al|por|cada)\s+mes\b', '', low)
    low = re.sub(r'\b(necesito|pido|prestamo de|al menos|minimo)\s+(?:de\s+)?(\d[\d,.]*)', r'\1 $\2', low)
    low = re.sub(r'\b(?:sin|no quiero|no acepto|no permito)\s+(?:los\s+)?pagos?\s+automaticos?\b', 'no autopay', low)
    low = re.sub(r'\bpagos?\s+automaticos?\b', 'autopay', low)
    low = re.sub(r'\b(sin|cero|no quiero)\s+(comisiones|cargos)\b', 'no fees', low)
    low = re.sub(r'\b(comision(?:es)?|cargos?)\s*(?:de|hasta)?\s*', 'fee ', low)
    low = re.sub(r'\b(?:pago mensual|pago al mes)\s*(?:de|hasta)?', 'monthly payment ', low)
    low = re.sub(r'\b(?:al|por|cada|a el)\s+mes\b|\bmensuales?\b', 'a month', low)
    low = re.sub(r'\b(?:gano|ganamos)\b', 'earn', low)
    low = re.sub(r'\b(?:ingresos?|sueldo)\b', 'income', low)
    low = re.sub(r'\balquiler\b', 'rent', low)
    low = re.sub(r'\bpor ciento\b', '%', low)
    low = re.sub(r'\b(\d+)\s*(?:a|y|hasta)\s*(\d+)\s*(meses|anos)\b', r'\1 to \2 \3', low)
    low = re.sub(r'\bmeses?\b', 'months', low)
    low = re.sub(r'\banos?\b', 'years', low)
    return low


def parse(user_texts):
    """Pull the limits out of the person's own messages with regexes. Later messages override earlier ones."""
    f = {}
    for t in user_texts:
        low = _spanish_text(t).lower()
        # a monthly payment first, then blank it out so it isn't also read as the loan amount, a fee or a term
        pays = sorted((m.start(), m.end(), m.group(1)) for rx in (PAY_AFTER, PAY_BEFORE) for m in rx.finditer(low))
        pays = [(a, b, v) for a, b, v in pays if _money(v)  # "I earn $3,000 a month" is income, not a limit
                and not re.search(r"\b(earn|earns|make|makes|making|income|salary|rent)\b", low[max(0, a - 30):a])]
        if pays:
            f["max_payment"] = _money(pays[-1][2])
            for a, b, _ in pays:
                low = low[:a] + " " * (b - a) + low[b:]
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
        one = re.findall(r"(\d+)\s*-?\s*(months?|mos?|years?|yrs?)\b", low) \
            or [(n, "months") for n in re.findall(r"\b(\d+)\s+monthly\s+(?:payments|installments)\b", low)]
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


def rule_reply(fields, lang="en"):
    if lang == "es":
        with language(lang):
            need = missing(fields)
            if need:
                return t("intake." + need[0])
            m = to_mandate(fields)
            reply = t("intake.summary", amount=money(m.amount), minimum=money(m.min_amount),
                      months=number(m.max_term), payment=money(m.max_payment) if m.max_payment else t("intake.not_set"),
                      rate=number(m.max_apr), autopay=t("intake.yes" if "autopay" in m.allow else "intake.no"), fee=money(m.max_fee))
            if m.max_payment and m.min_amount / m.max_term > m.max_payment:
                reply += t("intake.too_low")
            return reply + t("intake.confirm")
    need = missing(fields)
    if need:
        return QUESTIONS[need[0]]
    m = to_mandate(fields)
    limits = ([f"no more than ${m.max_payment:,.0f} a month"] if m.max_payment is not None else []) \
        + ([f"no more than {m.max_apr:g}% APR"] if fields.get("max_apr") is not None else [])
    reply = (f"Got it: up to ${m.amount:,.0f} (at least ${m.min_amount:,.0f}), {', '.join(limits)}, "
             + (f"{m.min_term}-{m.max_term} months, " if m.min_term < m.max_term else f"{m.max_term} months, ")
             + ("autopay OK, " if "autopay" in m.allow else "no autopay, ")
             + (f"fees up to ${m.max_fee:,.0f}." if m.max_fee else "no fees."))
    floor = m.min_amount / m.max_term  # the smallest possible payment: least amount, longest term, no interest
    if m.max_payment is not None and floor > m.max_payment:
        reply += (f" Heads up: even with no interest, ${m.min_amount:,.0f} over {m.max_term} months is "
                  f"${floor:,.0f} a month, more than your ${m.max_payment:,.0f}. A smaller amount or more months "
                  "would give lenders room.")
    return reply + " Shall I take this to the market?"


# ---------------------------------------------------------------- the agent

class MandateChat(ClaudeMixin):
    id = "intake"

    def __init__(self, client=None):
        self._setup_claude(client)

    def turn(self, messages, lang="en"):
        """messages = [{"role": "user"|"agent", "content": str}, ...], oldest first. Returns the agent's next turn."""
        if lang not in ("en", "es"):
            raise ValueError("unsupported language")
        self.language = lang
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
            reply, source = rule_reply(fields, lang), "rules"
        m = to_mandate(fields)
        return {"reply": reply, "fields": fields, "missing": missing(fields), "ready": m is not None,
                "mandate": mandate_dict(m), "source": source}

    def _claude(self, msgs):
        if not any(m["role"] == "user" for m in msgs):
            raise Fallback("nothing from the person yet")
        convo = "\n".join(f"{'Person' if m['role'] == 'user' else 'You (agent)'}: {m['content']}" for m in msgs)
        instruction = " Reply in natural, plain Spanish." if getattr(self, "language", "en") == "es" else " Reply in plain English."
        return self.ask(SYSTEM + instruction, "Conversation so far:\n" + convo + "\n\nReturn the fields and your reply as JSON.", SCHEMA)
