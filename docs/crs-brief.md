# CRS in one page

Source: https://calhacks.crscreditapi.com, plus our sandbox spec (`crs/calhacks-openapi-spec.json`).

## Who CRS is
A certified credit reporting agency in SF. They don't collect most of the data themselves. They plug into
Experian, TransUnion and Equifax (plus fraud, identity and records vendors) and sell it all through one API.
Their customers are lenders, landlords and fintechs who need to answer "who is this applicant, and can we trust them?"
Their pitch: getting approved to use bureau data normally takes months, and CRS skips that.

## What they want from us
Their brief: use CRS data to build an AI-native product that helps people or businesses **understand, protect,
improve, or act on** their financial profile. The only hard rule: **use the sandbox meaningfully and show it working live.**

Judging (no points formula; a bold idea counts as much as polish):
1. **Originality**: did it surprise them?
2. **Usefulness**: would someone actually use it?
3. **CRS at the core**: the data is what makes it work, not a bolt-on.
4. **It really works**: live, end-to-end demo.
5. **Responsible**: open about what it does with the data.

Prizes (one project can compete for several):

| Prize | Reward | What wins it |
|---|---|---|
| Best Overall CRS Hack | $1,000 | Most impressive product on CRS |
| Best Financial AI Agent | $500 | An agent that does real work, *not a chatbot that reads JSON* |
| Best Identity / Fraud Innovation | FDE interview, whole team | Protecting people or businesses from fraud and identity theft |
| Most Unexpected Use of CRS | FDE interview, whole team | "We didn't think of this" |

## What we actually have (sandbox)

| Product | Endpoint | What it tells you |
|---|---|---|
| Credit reports (TU / EFX / EXP) | `/{bureau}/credit-report/standard/...` | Every account, balance, late payment, inquiry, score. `prequal` = soft pull |
| Credit report PDFs | `/{bureau}/standard-credit-report/pdf/...` | The human-readable report, good for a UI |
| FraudFinder (AtData) | `/fraud-finder/...` | Email age and velocity, IP vs address distance, phone type and owner, risk score 0-100 |
| Identity verification (TU TruValidate) | `/transunion/identity-manager-verification/basic` | Does the SSN match the name, DOB, address? Deceased, frozen |
| Reverse lookup / append (AccurateAppend) | `/accurate-append/reverse`, `/phone/...`, `/email` | Who a phone/email/address actually belongs to |
| Liens, judgments, bankruptcies (PitchPoint) | `/pp/fcrablj/...` | Public-record financial history |
| Eviction search (CIC) | `/eviction/new-request` | Eviction filings |
| Criminal search (CIC) | `/criminal/new-request` | Criminal records (be careful: restricted for housing and hiring) |
| Batch append | `/accurate-append/s3/...`, `/jobs` | Upload a CSV and enrich many records at once |
| Your request log and retention | `/users/logs`, `/users/retention/{id}` | An audit trail of what you pulled; useful for the "responsible" criterion |

**Advertised on the CRS page but not in our sandbox spec:** prefill, business credit, OFAC/MLA compliance.
Ask at the booth before building on those.

**Test data:** 20 fixed fictional personas (P01-P20) in the Postman collection. We have saved responses for 5.
Use only these; never real people's data.

**Tools:** Postman collection (has your login, never commit it), MCP server for Claude Code
(`@crscreditapi/crs-calhacks-mcp-server`), and the CRS engineers at their booth all weekend.

## Directions we could take
Ranked by fit with how they judge.

1. **Applicant screening agent (what's in `agent/`).** Staged checks, stops early on fraud, tells
   "risky borrower" apart from "stolen identity", and catches what a single-bureau check misses.
   Hits Fraud + Agent + Overall. Make it more agentic by letting Claude pick the next check and explain why.
2. **Liveness-gated identity.** Add a live selfie / face anti-spoofing check to the step-up verification path.
   CRS has ID and document verification but no "is this a real face on camera" check. Strong for the Fraud prize.
3. **"Is my identity being used?" for consumers.** Flip it around: a person checks their own file and the agent
   flags inquiry bursts, unknown accounts and contact info that isn't theirs, then drafts the dispute or freeze.
   Fits CRS's "protect / improve" language and "Most Unexpected".
4. **Fair second look for thin files.** Students and new arrivals (like P03) get rejected for having little history.
   An agent that explains why they're actually low-risk is a strong "useful + responsible" story.
5. **Verified landlord, for renters.** Use CRS to verify the *landlord's* identity before a renter sends a deposit.
   Rental scams target students. Likely the most "unexpected" option.

## Things that will impress their judges
- Saying **soft pull vs hard pull** correctly, and only pulling what you need.
- Not running records on someone whose identity you don't trust (you'd be reading the victim's records).
- Showing the evidence behind every decision (which product, which field).
- Using all three bureaus and showing where they disagree (persona P17).
- Mentioning the FCRA: permissible purpose, consent, and adverse-action notices with reasons.
