"""Smoke test: calls every CRS sandbox product for a few personas and saves raw responses to samples/.

Needs CRS_USER and CRS_PASS in the environment (get them from the CRS portal Credentials page)
and the Postman collection next to this file (download it from the portal; DO NOT commit it, it holds the login).
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crs_client as C
c = C.CRS().login()
print("login ok")
prods = ["tu","efx","exp","fraudfinder","idv","blj","criminal","eviction","reverse"]
os.makedirs("samples", exist_ok=True)
for p in ["P03","P05","P13","P12","P17"]:
    for pr in prods:
        st, d = c.call(p, pr)
        json.dump({"_status": st, "body": d}, open(f"samples/{p}_{pr}.json", "w"), indent=2)
        print(p, pr, st)
