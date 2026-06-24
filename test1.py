import pickle, pathlib, requests

p = pathlib.Path.home() / ".tokens" / "robinhood.pickle"
data = pickle.loads(p.read_bytes())

resp = requests.post("https://api.robinhood.com/oauth2/token/", data={
    "grant_type": "refresh_token",
    "refresh_token": data["refresh_token"],
    "client_id": "c82SH0WZOsabOXGP2sxqcj34FxkvfnWRZBKlBjFS",
    "scope": "internal",
    "device_token": data["device_token"],
})
new_data = resp.json()
print("Status:", resp.status_code)
if "access_token" in new_data:
    data.update(new_data)
    p.write_bytes(pickle.dumps(data))
    print("\n✅ New access token (set as ROBINHOOD_TOKEN in Railway):\n")
    print(new_data["access_token"])
else:
    print("Error:", new_data)