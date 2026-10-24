"""Smoke test: calls every CRS sandbox product for the personas and saves raw responses to crs/samples/.

Needs CRS_USER and CRS_PASS in the environment (get them from the CRS portal Credentials page)
and the Postman collection next to this file (download it from the portal; DO NOT commit it, it holds the login).

    python3 crs/smoke_test.py              # all personas in the collection, skips ones already saved
    python3 crs/smoke_test.py P04 P09      # just these
    python3 crs/smoke_test.py --force      # re-fetch everything
"""
import json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crs_client as C

args = [a for a in sys.argv[1:] if not a.startswith("--")]
force = "--force" in sys.argv
c = C.CRS().login()
print("login ok")
prods = ["tu", "efx", "exp", "fraudfinder", "idv", "blj", "criminal", "eviction", "reverse"]
out_dir = os.path.join(HERE, "samples")
os.makedirs(out_dir, exist_ok=True)
personas = args or sorted(c.personas)
failed = []
for p in personas:
    for pr in prods:
        path = os.path.join(out_dir, f"{p}_{pr}.json")
        if os.path.exists(path) and not force:
            continue
        try:
            st, d = c.call(p, pr)
        except Exception as e:  # missing request in collection, timeout, etc.
            print(p, pr, "ERROR", e); failed.append(f"{p}_{pr}"); continue
        if st == 429:  # rate limited: wait and try once more
            time.sleep(int(c.last["headers"].get("Retry-After", 5))); st, d = c.call(p, pr)
        json.dump({"_status": st, "_latency_s": c.last.get("latency_s"), "_headers": c.last.get("headers"), "body": d},
                  open(path, "w"), indent=2)
        print(p, pr, st)
        if st != 200:
            failed.append(f"{p}_{pr}")
print(f"done: {len(personas)} personas" + (f", {len(failed)} not OK: {' '.join(failed)}" if failed else ", all OK"))
