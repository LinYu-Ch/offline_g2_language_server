# soak.py
import time, random, requests

URL = "http://127.0.0.1:8765/api/display"
END = time.time() + 45 * 60
sent = fails = 0
lat_max = 0.0

while time.time() < END:
    t0 = time.time()
    try:
        r = requests.post(URL, json={"text": f"{time.strftime('%H:%M:%S')} {random.randint(1000,9999)}"}, timeout=3)
        r.raise_for_status()
        sent += 1
    except Exception as e:
        fails += 1
        print(f"[{time.strftime('%H:%M:%S')}] FAIL {fails}: {e}", flush=True)
    lat_max = max(lat_max, time.time() - t0)
    if sent % 300 == 0 and sent:
        print(f"sent={sent} fails={fails} max_post_ms={lat_max*1000:.0f}", flush=True)
    time.sleep(max(0, 0.33 - (time.time() - t0)))

print(f"DONE sent={sent} fails={fails} max_post_ms={lat_max*1000:.0f}")
