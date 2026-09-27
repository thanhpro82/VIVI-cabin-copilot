#!/bin/bash
# Kiem suc khoe nhanh — chay hang ngay, hoac ngay truoc khi demo.
# Khac check_deploy_status.sh (12 nhom, dung khi dung may lan dau): file nay chi
# tra loi MOT cau — he thong co dang phuc vu duoc khong.
DOMAIN="c4-app-192.io.vn"
FAIL=0
ok()   { printf "  \033[32m[OK]\033[0m   %s\n" "$1"; }
bad()  { printf "  \033[31m[LOI]\033[0m  %s\n" "$1"; FAIL=1; }
warn() { printf "  \033[33m[!]\033[0m    %s\n" "$1"; }

echo "== 1. Ba container Docker =="
for svc in mqtt vehicle-simulator backend; do
  line=$(docker compose -f /opt/vivi/docker-compose.yml ps --format '{{.Service}} {{.Status}}' 2>/dev/null | grep "^$svc ")
  case "$line" in
    *healthy*) ok "$line" ;;
    *Up*)      warn "$line (dang chay, chua healthy)" ;;
    "")        bad "$svc: KHONG CHAY" ;;
    *)         bad "$line" ;;
  esac
done

echo
echo "== 2. Ba dich vu systemd =="
for svc in caddy vivi-frontend vivi-slm; do
  state=$(systemctl is-active "$svc" 2>/dev/null)
  [ "$state" = "active" ] && ok "$svc: active" || bad "$svc: $state"
done

echo
echo "== 3. Frontend tra ve 200 =="
code=$(curl -s -o /dev/null -w '%{http_code}' -L "http://127.0.0.1:3000/" 2>/dev/null)
[ "$code" = "200" ] && ok "127.0.0.1:3000 -> 200" || bad "127.0.0.1:3000 -> $code"

echo
echo "== 4. /healthz qua HTTPS that (di qua Caddy + chung chi) =="
health=$(curl -s --max-time 20 "https://$DOMAIN/healthz" 2>/dev/null)
if [ -z "$health" ]; then
  bad "Khong nhan duoc gi tu https://$DOMAIN/healthz"
else
  python3 - "$health" <<'PY'
import json, sys
try:
    d = json.loads(sys.argv[1])["data"]
except Exception as e:
    print(f"  \033[31m[LOI]\033[0m  Khong doc duoc JSON: {e}")
    sys.exit(1)
bad = 0
for name, c in d["components"].items():
    st = c["status"]
    ms = c.get("latency_ms") or 0
    if st == "ready":
        print(f"  \033[32m[OK]\033[0m   {name}: ready ({ms:.0f} ms)")
    elif st == "disabled":
        print(f"  \033[33m[!]\033[0m    {name}: disabled")
    else:
        print(f"  \033[31m[LOI]\033[0m  {name}: {st}")
        bad = 1
if d.get("faults"):
    for f in d["faults"]:
        print(f"  \033[33m[!]\033[0m    fault: {f.get('component')} = {f.get('code')}")
sys.exit(bad)
PY
  [ $? -ne 0 ] && FAIL=1
fi

echo
echo "== 5. Bundle frontend =="
n=$(grep -rl "localhost:8000" /opt/vivi/frontend/.next/static/ 2>/dev/null | wc -l)
[ "$n" -eq 0 ] && ok "Tro dung domain, khong con localhost:8000" \
                || bad "$n file con tro localhost:8000 — phai build lai frontend"

# Bien NEXT_PUBLIC_* la build-time. Ten bien CON SOT lai trong bundle nghia la
# no THIEU luc build (Next de nguyen process.env.X thanh tra cuu luc chay tren
# object rong -> luon undefined). Xem deploy_vps_fullstack.md muc 13.3.
w=$(grep -rlF "NEXT_PUBLIC_WAKE_WORD_ENABLED" /opt/vivi/frontend/.next/static/ 2>/dev/null | wc -l)
if [ "$w" -eq 0 ]; then
  ok "Wake word: co da duoc nuong vao bundle (muc 13.3 de doc true/false)"
else
  warn "Wake word: co THIEU luc build -> goi 'Hey ViVi' se khong an. Co y, khong phai loi."
fi

echo
echo "== 6. Tai nguyen =="
free -h | awk '/Mem:/{printf "  RAM:  %s dung / %s tong (con trong: %s)\n", $3, $2, $7}'
free -h | awk '/Swap:/{printf "  Swap: %s / %s\n", $3, $2}'
df -h / | awk 'NR==2{printf "  Dia:  %s dung / %s (%s)\n", $3, $2, $5}'
uptime | sed 's/^/  /'

echo
echo "== 7. Nhanh dang chay =="
cd /opt/vivi && printf "  %s @ %s\n" "$(git rev-parse --abbrev-ref HEAD)" "$(git rev-parse --short HEAD)"

# Hai phep kiem duoi day bat dung cai lam mat ca buoi sang 2026-08-23: container
# backend dung tu TRUOC khi co docker-compose.override.yml, va tu do chi duoc
# `restart` chu chua bao gio `up -d`. `restart` khong doc lai cau hinh, nen ca hai
# nua cua file override cung mat tac dung — trong khi `docker compose config` van
# in ra cau hinh dung. Trieu chung khi do: llm: down, va cong 8000 ho ra Internet.
echo
echo "== 8. Container backend co an file override chua =="
gw=$( (cd /opt/vivi && docker compose exec -T backend getent hosts host.docker.internal) 2>/dev/null | awk '{print $1}' )
if [ -n "$gw" ]; then
  ok "host.docker.internal -> $gw (backend goi duoc llama-server tren host)"
else
  bad "host.docker.internal KHONG phan giai duoc trong container -> llm se down"
  warn "Sua: cd /opt/vivi && docker compose up -d --force-recreate backend"
fi

binds=$(ss -tln 2>/dev/null | awk '$4 ~ /:8000$/ {print $4}' | tr '\n' ' ')
if [ -z "$binds" ]; then
  bad "Khong ai nghe cong 8000"
elif echo " $binds" | grep -qE ' (0\.0\.0\.0|\[::\]|\*):8000'; then
  bad "Cong 8000 mo ra ngoai ($binds) — API cong khai KHONG HTTPS, di vong qua Caddy"
  warn "ufw khong chan duoc cong do Docker publish. Sua: docker compose up -d --force-recreate backend"
else
  ok "Cong 8000 chi bind loopback ($binds)"
fi

echo
if [ "$FAIL" -eq 0 ]; then
  printf "\033[32m== TAT CA BINH THUONG ==\033[0m\n"
else
  printf "\033[31m== CO LOI — xem cac dong [LOI] o tren ==\033[0m\n"
  exit 1
fi
