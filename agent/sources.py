"""Where CRS responses come from: saved samples (offline, free) or the live sandbox."""
import json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(ROOT, "crs", "samples")


class SampleSource:
    """Reads crs/samples/<persona>_<product>.json. No credentials needed."""
    name = "samples"

    def __init__(self, folder=SAMPLES):
        self.folder = folder
        self.log = []  # one entry per product "call", for the audit trail

    def get(self, persona, product):
        path = os.path.join(self.folder, f"{persona}_{product}.json")
        if not os.path.exists(path):
            self.log.append({"product": product, "status": "missing"})
            return None
        d = json.load(open(path))
        self.log.append({"product": product, "status": d.get("_status"), "latency_s": d.get("_latency_s")})
        return d.get("body")

    def applicant(self, persona):
        """The details on the application (name, SSN, address), without counting as a product call."""
        path = os.path.join(self.folder, f"{persona}_tu.json")
        return (json.load(open(path)).get("body") or {}).get("requestData", {}) if os.path.exists(path) else {}

    def personas(self):
        return sorted({f.split("_")[0] for f in os.listdir(self.folder) if f.endswith(".json")})


class LiveSource:
    """Calls the CRS sandbox through crs/crs_client.py (needs CRS_USER, CRS_PASS and the collection)."""
    name = "live"

    _client, _login_error = None, None  # shared per process: log in once, never retry a failed login

    def __init__(self):
        # Repeated failed logins disable the CRS account, so a failed login is remembered and not retried
        # until the server restarts (fix the credentials first).
        if LiveSource._login_error:
            raise RuntimeError("CRS login failed earlier in this run; not retrying: " + LiveSource._login_error)
        if LiveSource._client is None:
            sys.path.insert(0, os.path.join(ROOT, "crs"))
            import crs_client
            try:
                LiveSource._client = crs_client.CRS().login()
            except Exception as e:
                LiveSource._login_error = type(e).__name__
                raise
        self.c = LiveSource._client
        self.log = []

    def get(self, persona, product):
        t = time.time()
        status, body = self.c.call(persona, product)
        self.log.append({"product": product, "status": status, "latency_s": round(time.time() - t, 2),
                         "request_id": self.c.last.get("headers", {}).get("RequestID")})
        return body if status == 200 and isinstance(body, dict) else None

    def applicant(self, persona):
        return self.c.body(persona, "tu")

    def personas(self):
        return sorted(self.c.personas)
