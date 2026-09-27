"""Hỏi backend thật qua /sessions + /turns/text. Dùng: python hoi.py "câu hỏi" [...]"""

import json
import sys
import time
import urllib.request

API = "http://127.0.0.1:8000/api/v1"
H = {"Content-Type": "application/json", "X-Schema-Version": "1.0"}


def goi(duong_dan, body=None, token=None, key=None):
    h = dict(H)
    if token:
        h["Authorization"] = f"Bearer {token}"
    if key:
        h["Idempotency-Key"] = key
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{duong_dan}", data=data, headers=h, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"LOI {e.code} tren {duong_dan}: {e.read().decode('utf-8', 'replace')[:400]}")
        raise SystemExit(1) from None


tok = goi("/auth/login", {"email": "driver.demo@example.com", "password": "DemoDriver123!"})["data"]["access_token"]
sid = goi("/sessions", {"vehicle_id": "vehicle-demo-01", "input_mode": "text"}, tok, key=f"s-{int(time.time()*1000)}")["data"]["session_id"]

for i, q in enumerate(sys.argv[1:]):
    t0 = time.perf_counter()
    out = goi("/turns/text", {"session_id": sid, "text": q}, tok, key=f"k-{int(t0 * 1000)}-{i}")["data"]
    ms = (time.perf_counter() - t0) * 1000
    out = out.get("response") or out
    print(f"\nHỎI  {q}")
    print(f"  outcome  {out.get('outcome')}   {ms:.0f} ms")
    print(f"  NÓI      {out.get('speak_text') or out.get('response_text')}")
    hien = out.get("display_text") or ""
    noi = out.get("speak_text") or ""
    if hien and hien != noi:
        print(f"  MÀN      {hien[:300]}")
