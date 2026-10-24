"""Minimal client for the CRS Credit API sandbox (Cal Hacks 13.0).

Reads CRS_USER / CRS_PASS from the environment. Persona request bodies are
loaded by name from the Postman collection (CRS_COLLECTION, default
calhacks13-20261024-CRS-Sandbox.json next to this file).
"""
import json, os, re, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
COLLECTION = os.environ.get("CRS_COLLECTION", os.path.join(HERE, "calhacks13-20261024-CRS-Sandbox.json"))
BASE = "https://api-sandbox.stitchcredit.com/api"  # sandbox only

# product -> (persona request name in collection, path)
PRODUCTS = {
    "tu":          ("TransUnion credit report", "/transunion/credit-report/standard/tu-prequal-fico9"),
    "efx":         ("Equifax credit report", "/equifax/credit-report/standard/efx-prequal-vantage4"),
    "exp":         ("Experian credit report", "/experian/credit-report/standard/exp-prequal-vantage4"),
    "fraudfinder": ("AtData FraudFinder", "/fraud-finder/fraud-finder"),
    "idv":         ("TransUnion identity verification (TUC3002)", "/transunion/identity-manager-verification/basic"),
    "blj":         ("PitchPoint FCRA BLJ (data)", "/pp/fcrablj/data"),
    "criminal":    ("Criminal search", "/criminal/new-request"),
    "eviction":    ("Eviction search", "/eviction/new-request"),
    "reverse":     ("AccurateAppend Reverse Unified", "/accurate-append/reverse"),
}


def load_personas(path=COLLECTION):
    """Return {'P01': {request_name: body_dict, ...}, ...}."""
    with open(path) as f:
        col = json.load(f)
    out = {}
    def walk(items):
        for it in items:
            if "item" in it:
                m = re.match(r"(P\d\d)\b", it["name"])
                if m:
                    out[m.group(1)] = {
                        sub["name"]: json.loads(sub["request"]["body"]["raw"])
                        for sub in it["item"] if sub.get("request", {}).get("body")
                    }
                else:
                    walk(it["item"])
    walk(col["item"])
    return out


class CRS:
    def __init__(self, user=None, password=None, collection=COLLECTION):
        self.user = user or os.environ["CRS_USER"]
        self._pw = password or os.environ["CRS_PASS"]
        self.s = requests.Session()
        self.s.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        self.personas = load_personas(collection)
        self.token = self.refresh = None
        self.last = {}  # latency/status/headers of last call

    def login(self):
        r = self.s.post(BASE + "/users/login", json={"username": self.user, "password": self._pw}, timeout=60)
        r.raise_for_status()
        d = r.json()
        self.token, self.refresh = d.get("token"), d.get("refreshToken")
        self.s.headers["Authorization"] = "Bearer " + self.token
        return self

    def refresh_token(self):
        r = self.s.post(BASE + "/users/refresh-token", json={"refreshToken": self.refresh}, timeout=60)
        r.raise_for_status()
        d = r.json()
        self.token = d.get("token", self.token)
        self.s.headers["Authorization"] = "Bearer " + self.token
        return d

    def body(self, persona, product):
        return self.personas[persona][PRODUCTS[product][0]]

    def call(self, persona, product, retry_auth=True):
        """POST the persona's body to the product endpoint -> (status, json_or_text)."""
        if not self.token:
            self.login()
        t = time.time()
        r = self.s.post(BASE + PRODUCTS[product][1], json=self.body(persona, product), timeout=120)
        if r.status_code == 401 and retry_auth:
            self.login(); return self.call(persona, product, False)
        self.last = {"status": r.status_code, "latency_s": round(time.time() - t, 2),
                     "headers": {k: v for k, v in r.headers.items()
                                 if k.lower() in ("requestid", "retry-after") or "ratelimit" in k.lower() or k.lower().startswith("x-rate")}}
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, r.text

    # one function per product
    def credit_report_tu(self, p): return self.call(p, "tu")
    def credit_report_efx(self, p): return self.call(p, "efx")
    def credit_report_exp(self, p): return self.call(p, "exp")
    def fraud_finder(self, p): return self.call(p, "fraudfinder")
    def identity_verification(self, p): return self.call(p, "idv")
    def liens_judgments(self, p): return self.call(p, "blj")
    def criminal(self, p): return self.call(p, "criminal")
    def eviction(self, p): return self.call(p, "eviction")
    def reverse_append(self, p): return self.call(p, "reverse")

    def error_codes(self):
        return self.s.get(BASE + "/sys/errors", timeout=60).json()


def retrieve_report(client, persona, product, request_id):
    """Step 3 of the credit flow: re-fetch a prior order by RequestID (body = same persona body)."""
    path = PRODUCTS[product][1] + "/" + request_id
    r = client.s.post(BASE + path, json=client.body(persona, product), timeout=120)
    return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
