#!/bin/bash
# Dieu tra dia va RAM tren VPS — CHI DOC, khong xoa gi, khong restart gi.
#
# Vi sao can file rieng thay vi them vao health.sh: health.sh tra loi "he co dang
# phuc vu duoc khong" trong vai giay. File nay tra loi "cho nao an het dia" va no
# phai `du` ca cay thu muc, mat vai chuc giay. Tron hai muc dich vao mot script la
# cach chac chan de khong ai chay cai nao nua.
#
# Doc ket qua theo thu tu: muc 2 (Docker) truoc, vi day la may build image lai
# nhieu lan. Chi khi muc 2 sach moi doc tiep xuong duoi.
#
#   bash /opt/vivi/deploy/vps/kiem_dung_luong.sh

set -uo pipefail

REPO=/opt/vivi
NGUONG_CANH_BAO=85   # % dia, tren muc nay thi in canh bao do

d()    { printf "\n\033[1m== %s ==\033[0m\n" "$1"; }
ok()   { printf "  \033[32m[OK]\033[0m   %s\n" "$1"; }
bad()  { printf "  \033[31m[LOI]\033[0m  %s\n" "$1"; }
warn() { printf "  \033[33m[!]\033[0m    %s\n" "$1"; }
note() { printf "         %s\n" "$1"; }

# `du` tren mot so thu muc he thong doi root. Chay duoc sudo khong hoi mat khau
# thi dung, khong thi bo qua va noi ro la so bi thieu — dung im lang tra so nho.
if sudo -n true 2>/dev/null; then SUDO=sudo; else SUDO=""; fi

d "1. Tong quan"
df -h / | awk 'NR==2{printf "  Dia:  %s dung / %s (%s), con trong %s\n", $3, $2, $5, $4}'
PCT=$(df -h / | awk 'NR==2{gsub("%","",$5); print $5}')
# Bao ve bang `case`: `[ "" -ge 85 ]` la loi cu phap cua test, va voi `set -u` thi
# no van khong dung script lai — chi im lang in mot dong loi giua bang.
case "$PCT" in
  ''|*[!0-9]*) warn "khong doc duoc % dia tu df" ;;
  *) [ "$PCT" -ge "$NGUONG_CANH_BAO" ] && bad "Dia da dung $PCT% — tren nguong $NGUONG_CANH_BAO%" ;;
esac
# `free` cot "used" da tru buff/cache. In ca hai de khong ai nham cache thanh ro ri:
# cache la RAM DANG RANH duoc muon, kernel tra lai ngay khi co ai can.
free -h | awk '/Mem:/{printf "  RAM:  %s dung / %s tong | buff/cache %s | kha dung %s\n", $3, $2, $6, $7}'
free -h | awk '/Swap:/{printf "  Swap: %s / %s\n", $3, $2}'
[ -n "$SUDO" ] || warn "Khong co sudo khong mat khau — vai thu muc he thong se bi bo qua o muc 4"

d "2. Docker — nghi can so mot"
if ! command -v docker >/dev/null 2>&1; then
  warn "khong co docker"
else
  docker system df 2>/dev/null | sed 's/^/  /'
  echo
  # RECLAIMABLE la con so quan trong nhat ca script. Build cache thuong chiem phan
  # lon o may build lai nhieu lan, va no KHONG duoc don tu dong.
  CACHE=$(docker system df --format '{{.Type}}\t{{.Size}}\t{{.Reclaimable}}' 2>/dev/null | awk -F'\t' '/Build Cache/{print $2}')
  DANGLING=$(docker images -f dangling=true -q 2>/dev/null | wc -l)
  note "Build cache: ${CACHE:-?}   |   image mo coi (dangling): $DANGLING"
  if [ "${DANGLING:-0}" -gt 0 ]; then
    warn "$DANGLING image mo coi — moi lan \`docker compose build backend\` de lai mot cai"
  fi
  echo
  echo "  -- image theo kich thuoc --"
  docker images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}' 2>/dev/null \
    | sort -k2 -h -r | head -12 | sed 's/^/  /'
  echo
  echo "  -- log cua tung container --"
  # Log container mac dinh KHONG co gioi han xoay vong tren Docker; mot container
  # chay lien 4 ngay co the mot minh chiem vai GB.
  for cid in $(docker ps -aq 2>/dev/null); do
    name=$(docker inspect --format '{{.Name}}' "$cid" 2>/dev/null | tr -d /)
    lf=$(docker inspect --format '{{.LogPath}}' "$cid" 2>/dev/null)
    if [ -n "$lf" ] && [ -n "$SUDO" ]; then
      sz=$($SUDO du -h "$lf" 2>/dev/null | cut -f1)
      printf "  %-22s %s\n" "$name" "${sz:-?}"
    else
      printf "  %-22s (can sudo de doc)\n" "$name"
    fi
  done
  echo
  echo "  -- gioi han xoay vong log --"
  if [ -f /etc/docker/daemon.json ] && grep -q "max-size" /etc/docker/daemon.json 2>/dev/null; then
    ok "daemon.json co dat max-size"
  else
    warn "daemon.json KHONG dat log max-size -> log container tang khong gioi han"
  fi
fi

d "3. Journald"
if command -v journalctl >/dev/null 2>&1; then
  journalctl --disk-usage 2>/dev/null | sed 's/^/  /'
  LIM=$(grep -E '^\s*SystemMaxUse=' /etc/systemd/journald.conf 2>/dev/null | head -1)
  [ -n "$LIM" ] && ok "journald.conf: $LIM" || warn "journald.conf khong dat SystemMaxUse -> mac dinh la 10% dia"
fi

d "4. Thu muc lon nhat toan may"
# -x: khong vuot sang filesystem khac (bo qua /proc, /sys, mount la).
$SUDO du -xh --max-depth=1 / 2>/dev/null | sort -h -r | head -12 | sed 's/^/  /'

d "5. Ben trong /var (docker va log thuong nam day)"
$SUDO du -xh --max-depth=2 /var 2>/dev/null | sort -h -r | head -12 | sed 's/^/  /'

d "6. Ben trong $REPO"
if [ -d "$REPO" ]; then
  $SUDO du -xh --max-depth=2 "$REPO" 2>/dev/null | sort -h -r | head -15 | sed 's/^/  /'
  echo
  # Bon thu muc nay lon nhung KHAC nhau ve tinh chat: models/tools tai lai duoc,
  # eval/results la bang chung khong tai lai duoc. Tach ra de khong ai xoa nham.
  for p in models tools frontend/node_modules frontend/.next eval/results data; do
    [ -e "$REPO/$p" ] && printf "  %-26s %s\n" "$p" "$($SUDO du -sh "$REPO/$p" 2>/dev/null | cut -f1)"
  done
fi

d "7. Thu muc home"
$SUDO du -xh --max-depth=1 "$HOME" 2>/dev/null | sort -h -r | head -10 | sed 's/^/  /'
for p in .cache/pip .npm vivi-runs vivi-cuu-vps; do
  [ -e "$HOME/$p" ] && printf "  %-26s %s\n" "$p" "$($SUDO du -sh "$HOME/$p" 2>/dev/null | cut -f1)"
done

d "8. File da xoa ma tien trinh van giu"
# Truong hop kinh dien "df bao day nhung du khong tim ra": mot tien trinh chay lau
# van mo file log da bi xoa, nen inode chua duoc giai phong. `du` khong thay,
# `df` van tinh. Chi restart tien trinh do moi tra lai cho.
if command -v lsof >/dev/null 2>&1; then
  OUT=$($SUDO lsof -nP +L1 2>/dev/null | awk 'NR==1 || $7+0 > 100000000')
  if [ "$(printf '%s\n' "$OUT" | wc -l)" -le 1 ]; then
    ok "Khong co file da xoa nao con bi giu tren 100 MB"
  else
    bad "Co file da xoa van bi giu — restart tien trinh tuong ung moi lay lai duoc cho:"
    printf '%s\n' "$OUT" | sed 's/^/  /'
  fi
else
  warn "khong co lsof (cai: sudo apt install lsof) — bo qua phep kiem nay"
fi

d "9. RAM theo tien trinh"
echo "  -- 10 tien trinh ton RAM nhat (RSS) --"
ps -eo rss=,pid=,comm= --sort=-rss 2>/dev/null | head -10 \
  | awk '{printf "  %8.1f MB  pid %-8s %s\n", $1/1024, $2, $3}'
echo
if command -v docker >/dev/null 2>&1; then
  echo "  -- RAM tung container --"
  docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}' 2>/dev/null | sed 's/^/  /'
fi

d "10. Cai gi lay lai duoc"
echo "  Doc muc 2 truoc. Ba lenh duoi day theo thu tu AN TOAN GIAM DAN —"
echo "  chay tung cai, xem lai df, dung ngay khi du cho."
echo
echo "  1) Build cache (an toan nhat, chi lam lan build sau cham hon):"
echo "       docker builder prune -f"
echo
echo "  2) Image mo coi (khong con tag, khong container nao dung):"
echo "       docker image prune -f"
echo
echo "  3) Log journald, giu lai 3 ngay gan nhat:"
echo "       sudo journalctl --vacuum-time=3d"
echo
warn "KHONG chay \`docker system prune -a\`: no xoa ca image dang duoc dung boi"
note "container da dung, va \`docker compose build backend\` mat ~8,6 phut de dung lai."
echo
echo "  Ba thu KHONG duoc xoa: eval/results/ (bang chung, khong tai lai duoc),"
echo "  data/ (chi muc FAISS), models/ (2 GB nhung phai tai lai qua mang)."
