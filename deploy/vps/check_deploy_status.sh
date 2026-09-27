#!/bin/bash
ok()   { printf "  [OK]   %s\n" "$1"; }
miss() { printf "  [MISS] %s\n" "$1"; }
warn() { printf "  [WARN] %s\n" "$1"; }

echo "== A. Caddy / HTTPS =="
systemctl is-active caddy 2>/dev/null | xargs -I{} echo "  caddy service: {}"
curl -s -o /dev/null -w "  https://c4-app-192.io.vn/healthz -> %{http_code}\n" https://c4-app-192.io.vn/healthz

echo
echo "== B. CORS_ORIGINS trong .env =="
grep "^CORS_ORIGINS=" /opt/vivi/.env || miss "khong co dong CORS_ORIGINS"

echo
echo "== C. Backend image co moi khong (co vai classify cua PR #232 khong) =="
docker compose -f /opt/vivi/docker-compose.yml exec -T backend python -c "from src.agents import slm; print('classify: OK neu khong loi' )" 2>&1 | tail -3
docker images --format "{{.Repository}}:{{.Tag}}  {{.CreatedSince}}" | grep -i vivi

echo
echo "== D. docker-compose.override.yml — co extra_hosts khong =="
cat /opt/vivi/docker-compose.override.yml 2>/dev/null || miss "khong co file"

echo
echo "== E. SLM_ENDPOINT + SLM_ENABLED trong .env =="
grep -E "^SLM_ENDPOINT=|^SLM_ENABLED=|^SLM_TIMEOUT_S=|^OMP_NUM_THREADS=" /opt/vivi/.env

echo
echo "== F. ufw co luat cho 8093 tu mang Docker khong =="
sudo ufw status | grep -i 8093 || miss "chua co luat"

echo
echo "== G. vivi-slm.service =="
systemctl is-active vivi-slm 2>/dev/null | xargs -I{} echo "  service: {}"
ps -o args= -C llama-server | grep -o '\-t [0-9]*'
curl -s http://127.0.0.1:8093/health 2>&1

echo
echo "== H. Backend co goi duoc llama-server qua host.docker.internal khong =="
docker compose -f /opt/vivi/docker-compose.yml exec -T backend sh -c "python3 -c \"import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:8093/health', timeout=5).read())\"" 2>&1 | tail -5

echo
echo "== I. /healthz thuc te qua HTTPS noi ve llm =="
curl -s https://c4-app-192.io.vn/healthz 2>/dev/null | python3 -m json.tool 2>/dev/null | grep -A3 '"llm"'

echo
echo "== J. Frontend .env.production dung ten mien nao =="
cat /opt/vivi/frontend/.env.production 2>/dev/null || miss "khong co file"

echo
echo "== K. Bundle frontend con troi localhost:8000 khong =="
n=$(grep -rl "localhost:8000" /opt/vivi/frontend/.next/static/ 2>/dev/null | wc -l)
if [ "$n" -eq 0 ]; then ok "sach, khong con localhost:8000"; else warn "$n file con troi localhost:8000 — PHAI build lai"; fi

echo
echo "== L. vivi-frontend service =="
systemctl is-active vivi-frontend 2>/dev/null | xargs -I{} echo "  service: {}"
