#!/bin/bash
# Kiem toan bo trang thai sau khi nang cap vCPU/RAM. Nang cap thuong keo theo
# MOT LAN reboot; script nay phan biet "mat that" (dang lo) voi "chua reboot lai
# duoc" (chi can khoi dong lai dich vu).
ok()   { printf "  [OK]   %s\n" "$1"; }
miss() { printf "  [MISS] %s\n" "$1"; }
warn() { printf "  [WARN] %s\n" "$1"; }

echo "== 1. May va uptime =="
echo "  vCPU: $(nproc)   RAM: $(free -h | awk '/Mem:/{print $2}')"
echo "  Uptime: $(uptime -p 2>/dev/null || uptime)"
echo "  -> uptime duoi 10 phut nghia la vua reboot that; may chay lien tuc thi khong"

echo
echo "== 2. File cau hinh tren dia (KHONG qua Docker, KHONG qua systemd) =="
for f in /opt/vivi/.env \
         /opt/vivi/config/mosquitto/passwd \
         /opt/vivi/frontend/.env.production \
         /opt/vivi/frontend/.env.runtime \
         /opt/vivi/docker-compose.override.yml \
         /etc/caddy/Caddyfile; do
  if [ -s "$f" ]; then ok "$f ($(stat -c%s "$f") byte)"; else miss "$f"; fi
done

echo
echo "== 3. Model va llama.cpp (khong qua git, khong tu dong tai lai duoc) =="
for f in /opt/vivi/models/slm/qwen2.5-3b-instruct-q4_k_m.gguf \
         /opt/vivi/tools/llama/llama-b10358/llama-server \
         /opt/vivi/tools/llama/llama-b10358/llama-bench; do
  if [ -f "$f" ]; then ok "$f ($(du -h "$f" | cut -f1))"; else miss "$f"; fi
done

echo
echo "== 4. Chung chi HTTPS (mat cai nay thi phai xin lai, tinh vao han muc) =="
if sudo test -d /var/lib/caddy/.local/share/caddy/certificates 2>/dev/null; then
  n=$(sudo find /var/lib/caddy/.local/share/caddy/certificates -name "*.crt" 2>/dev/null | wc -l)
  if [ "$n" -gt 0 ]; then ok "co $n chung chi da cap"; else miss "thu muc rong"; fi
else
  miss "/var/lib/caddy/.local/share/caddy/certificates"
fi

echo
echo "== 5. Docker: container co tu khoi dong lai sau reboot khong =="
cd /opt/vivi 2>/dev/null && docker compose ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null

echo
echo "== 6. systemd: dich vu co dang chay khong =="
for svc in caddy vivi-frontend vivi-slm; do
  if systemctl list-unit-files 2>/dev/null | grep -q "^$svc.service"; then
    state=$(systemctl is-active "$svc" 2>/dev/null)
    if [ "$state" = "active" ]; then ok "$svc: active"; else warn "$svc: $state"; fi
  else
    warn "$svc: chua cai (khong phai loi neu chua toi buoc do)"
  fi
done

echo
echo "== 7. llama-server co dang chay khong (thuong chi trong tmux, KHONG song qua reboot) =="
if pgrep -x llama-server >/dev/null; then
  ok "dang chay: $(ps -o args= -C llama-server)"
else
  warn "khong chay — binh thuong neu vua reboot va no chi chay trong tmux truoc do"
fi
tmux ls 2>/dev/null && echo "  (phien tmux con song ke tren)" || echo "  khong con phien tmux nao"

echo
echo "== 8. Khoa SSH — con dang nghe la con dang ket noi duoc =="
if [ -s ~/.ssh/authorized_keys ]; then ok "authorized_keys co $(wc -l < ~/.ssh/authorized_keys) dong"; else miss "authorized_keys"; fi

echo
echo "== 9. Dia con trong bao nhieu (nang cap RAM/CPU khong lam mat dia, nhung kiem cho chac) =="
df -h / | tail -1
