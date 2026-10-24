# CRS Credit API sandbox client (Cal Hacks 13.0)

Sandbox only: `https://api-sandbox.stitchcredit.com/api`. Never commit credentials.

## Files
- `crs_client.py` - client (requests). `CRS().login()`, then `credit_report_tu/efx/exp`, `fraud_finder`,
  `identity_verification`, `liens_judgments`, `criminal`, `eviction`, `reverse_append`, `error_codes`.
  Persona bodies (P01-P20) are loaded by name from the Postman collection.
- `smoke_test.py` - calls every product for P03/P05/P13/P12/P17 and saves raw responses to `samples/`.
  (response + status, latency, RequestID/rate-limit headers).
- `samples/` - saved raw responses. Contain only fictional persona data.

## Run
    pip install requests
    export CRS_USER='<sandbox username>'   # from your CRS sandbox email/collection
    export CRS_PASS='<sandbox password>'
    python3 -c "
    import crs_client as C
    c = C.CRS().login()
    st, d = c.credit_report_tu('P05'); print(st, d['scores'][0]['scoreValue'], c.last['latency_s'])
    st, ff = c.fraud_finder('P13');   print(ff['risk']['score'])"

The collection JSON must sit next to `crs_client.py` (or set `CRS_COLLECTION=/path/to/collection.json`).

## Notes
- Auth: `POST /users/login {username,password}` -> `{token, refreshToken}`; send `Authorization: Bearer <token>`.
- Credit/FraudFinder/IDV are single synchronous POSTs; response header `RequestID` allows step-3 retrieve
  (`retrieve_report`, same body POSTed to `.../<RequestID>`).
- Collection personas are deterministic fixtures: use their request bodies as-is.
