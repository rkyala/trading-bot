import robin_stocks.robinhood as rh
import robin_stocks.robinhood.authentication as auth
import json, requests

user = input("Robinhood email: ").strip()
pw   = input("Robinhood password: ").strip()
mfa  = input("MFA code (leave blank if none): ").strip()

# Patch to print raw response
orig = requests.post
def patched_post(url, *a, **kw):
    r = orig(url, *a, **kw)
    print("URL:", url)
    print("Response:", r.status_code, r.text[:500])
    return r
requests.post = patched_post

try:
    rh.login(username=user, password=pw,
             store_session=True, mfa_code=mfa or None)
except Exception as e:
    print("Error:", e)


    import base64, pathlib
p = pathlib.Path.home() / '.tokens' / 'robinhood.pickle'
print(base64.b64encode(p.read_bytes()).decode())