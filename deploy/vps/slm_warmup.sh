#!/bin/bash
# Nap san tien to 562 token vao KV cache cua llama-server.
#
# Vi sao can: src/agents/slm.py:155 ghep prompt la
#   SLM_UNION_PROMPT (1791 ky tu ~ 562 token, HANG SO) + cau tai xe (~15 token)
# Luot dau tien sau khi server khoi dong phai prefill ca 562 token. Do duoc tren
# may nay 2026-08-22: 28 733 ms, tong luot 35 637 ms — vuot moi tran timeout hop
# ly, va graph.py con thu lai mot lan nua. Cac luot sau chi prefill 8-12 token vi
# tien to da nam trong cache.
#
# LUON exit 0. Day chay o ExecStartPost; thoat khac 0 thi systemd coi unit that
# bai va GIET llama-server. Warm-up hong chi lam luot dau cham, khong duoc phep
# lam chet ca dich vu.
set -u

ENDPOINT="${SLM_ENDPOINT_LOCAL:-http://127.0.0.1:8093}"
PROMPT_FILE="${SLM_PROMPT_FILE:-/opt/vivi/scripts/spike3_prompt.txt}"
DEADLINE=$(( $(date +%s) + 120 ))

# 1. Cho server san sang. Type=simple nen systemd chay buoc nay ngay sau khi fork,
#    truoc luc llama-server kip nap model.
until curl -sf "$ENDPOINT/health" >/dev/null 2>&1; do
  if [ "$(date +%s)" -ge "$DEADLINE" ]; then
    echo "warmup: server khong len sau 120s — bo qua, luot dau se cham"
    exit 0
  fi
  sleep 1
done

if [ ! -r "$PROMPT_FILE" ]; then
  echo "warmup: khong doc duoc $PROMPT_FILE — bo qua, luot dau se cham"
  exit 0
fi

# 2. Ban mot luot voi dung tien to. n_predict=1 vi chi can tra tien prefill;
#    decode khong lam am them cai gi.
#    Da xac minh 2026-08-22: spike3_prompt.txt GIONG HET SLM_UNION_PROMPT
#    (1791 ky tu, 28 dong). Kiem lai bang lenh o runbook muc 8.3f khi slm.py doi.
python3 - "$ENDPOINT" "$PROMPT_FILE" <<'PY'
import json
import sys
import urllib.request

endpoint, prompt_file = sys.argv[1], sys.argv[2]
with open(prompt_file, encoding="utf-8") as f:
    prefix = f.read()

body = json.dumps({
    "prompt": prefix + "Dat dieu hoa 22 do\nJSON:",
    "temperature": 0,
    "n_predict": 1,
    "cache_prompt": True,
}).encode("utf-8")

req = urllib.request.Request(
    endpoint + "/completion", data=body,
    headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=180) as r:
        t = json.load(r).get("timings", {})
    print("warmup: prefill {} token trong {:.0f} ms — cache da am".format(
        t.get("prompt_n"), t.get("prompt_ms") or 0))
except Exception as exc:                       # noqa: BLE001 — fail-open co chu y
    print("warmup: that bai ({}) — bo qua, luot dau se cham".format(exc))
PY

exit 0
