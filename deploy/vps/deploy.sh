#!/bin/bash
# Goi lai quy trinh cap nhat code cua docs/deploy_vps_cap_nhat_code.md thanh MOT
# lenh. Tu quyet dinh co can rebuild backend/frontend hay khong dua tren file
# thuc su thay doi giua hai lan git pull.
#
# KHONG lam thay: doi .env, Caddyfile, vivi-slm.service, vivi-frontend.service —
# nhung file do doi hiem va nen lam co y thuc, xem muc 4/5/6 cua doc tren.
set -euo pipefail

# Bash doc script theo KHOI va nho offset trong file, con buoc 2 duoi day
# (`git merge --ff-only`) ghi de chinh file nay trong luc no dang chay. Khi file
# vuot 8 KB — dung kich thuoc khoi doc cua bash — phan chua chay se duoc doc tiep
# tu offset cu tren NOI DUNG MOI, tuc bash nhay vao giua mot dong bat ky. File nay
# da qua 8 KB sau ban va vong lap cho `/healthz`, nen tu chay lai tu mot ban sao:
# ban sao nam ngoai repo, `git merge` khong dung toi.
if [ -z "${VIVI_DEPLOY_SELFCOPY:-}" ]; then
  SELF_COPY=$(mktemp /tmp/vivi-deploy.XXXXXX.sh)
  trap 'rm -f "$SELF_COPY"' EXIT
  cat "$0" > "$SELF_COPY"
  export VIVI_DEPLOY_SELFCOPY=1
  rc=0
  bash "$SELF_COPY" "$@" || rc=$?
  exit "$rc"
fi

DOMAIN="c4-app-192.io.vn"
REPO=/opt/vivi

ok()   { printf "  [OK]   %s\n" "$1"; }
info() { printf "  [..]   %s\n" "$1"; }
warn() { printf "  [WARN] %s\n" "$1"; }
err()  { printf "  [LOI]  %s\n" "$1" >&2; }

# Canh bao tmux CHI danh cho nguoi go tay. `[ -t 1 ]` kiem stdout co phai terminal
# khong — CD vao qua SSH voi `no-pty` nen khong co TTY, dieu kien nay sai va ca
# khoi bi bo qua. Dung vi CD khong the "dong terminal giua chung": GitHub Actions
# giu ket noi suot job, va co `sleep 5` o day chi lam moi lan deploy cham them 5
# giay ma khong bao ve duoc gi.
if [ -z "${TMUX:-}" ] && [ -t 1 ]; then
  warn "Dang KHONG chay trong tmux. Neu phai rebuild backend (vai phut), mang rot"
  warn "giua chung se lam build do dang. Nen Ctrl+C, 'tmux new -s deploy', roi chay"
  warn "lai. Tiep tuc sau 5 giay neu co y chay thang..."
  sleep 5
fi

cd "$REPO"

echo "== 1. Kiem cay lam viec truoc khi pull =="
# Nhung file duoc phep dang do (da biet ly do, xem deploy_vps_van_hanh.md):
# 4 file metadata giong noi chi khac CRLF/LF, va spike3_bench.py la ban va RSS
# cho Linux chua tung qua git commit.
ALLOWED_DIRTY="models/voice/vi_VN-piper.onnx.json.metadata.json
models/voice/vi_VN-piper.onnx.json.sha256
models/voice/vi_VN-piper.onnx.metadata.json
models/voice/vi_VN-piper.onnx.sha256
scripts/spike3_bench.py"

UNEXPECTED=""
while IFS= read -r line; do
  status="${line:0:2}"
  file="${line:3}"
  case "$status" in
    " M"|"M "|"MM")
      if ! grep -qxF "$file" <<< "$ALLOWED_DIRTY"; then
        UNEXPECTED="${UNEXPECTED}${file}"$'\n'
      fi
      ;;
  esac
done < <(git status --porcelain)

if [ -n "$UNEXPECTED" ]; then
  err "Co file da sua TAY ngoai danh sach da biet — DUNG LAI, khong tu y pull:"
  printf '%s' "$UNEXPECTED" | sed 's/^/    /'
  err "Xem tay bang 'git diff <file>' truoc khi chay lai script nay."
  exit 1
fi
ok "Cay lam viec sach (hoac chi co thay doi da biet)"

echo
echo "== 2. git pull =="
OLD_HEAD=$(git rev-parse HEAD)
CUR_BRANCH=$(git rev-parse --abbrev-ref HEAD)
# Nhanh trien khai: mac dinh la nhanh dang checkout. CD dat DEPLOY_REF=main.
DEPLOY_REF="${DEPLOY_REF:-$CUR_BRANCH}"
info "Nhanh trien khai: $DEPLOY_REF (dang o: $CUR_BRANCH)"

git fetch origin "$DEPLOY_REF"
TARGET=$(git rev-parse "origin/$DEPLOY_REF")

if [ "$DEPLOY_REF" = "$CUR_BRANCH" ]; then
  # CUNG NHANH: chong lui phien ban. Tren mot nhanh, di lui gan nhu luon la sai
  # (fetch hong, ai do force-push, hoac go nham). Tu choi.
  if [ "$TARGET" != "$OLD_HEAD" ] && git merge-base --is-ancestor "$TARGET" "$OLD_HEAD"; then
    err "TU CHOI: origin/$DEPLOY_REF (${TARGET:0:7}) la to tien cua ban dang chay (${OLD_HEAD:0:7})."
    err "Tren cung mot nhanh, day la di lui — gan nhu chac chan la nham."
    exit 1
  fi
  git merge --ff-only "origin/$DEPLOY_REF"
else
  # DOI NHANH: co chu y, cho phep — ke ca khi nhanh dich "cu" hon theo nghia
  # git. Vi du that: deploy tay `develop` de test, sau do CD tra ve `main`;
  # main luc do co the sau develop vai commit nhung VAN la ban production dung.
  # Ap luat chong lui o day se chan dung luong lam viec da chon.
  warn "DOI NHANH: $CUR_BRANCH -> $DEPLOY_REF"

  # `git checkout` tu choi khi co file dang sua do. Bon file metadata giong noi
  # luon "ban" tren VPS vi da scp tu Windows (CRLF) de len ban trong index (LF,
  # do .gitattributes ep `* text=auto eol=lf`). NOI DUNG GIONG HET.
  #
  # PHAI lay danh sach tu `git status --porcelain`, KHONG dung
  # `git diff --name-only`: voi truong hop chi khac CRLF, `git diff` chuan hoa
  # xuong dong truoc khi so nen tra ve RONG, trong khi `git status` van bao ` M`
  # va `git checkout` van tu choi. Dung `git diff` de liet ke thi vong nay tim
  # khong ra file nao va khong cuu duoc gi.
  #
  # Sau khi co danh sach, dung `git diff --quiet` de PHAN LOAI: tra 0 = khong
  # khac noi dung (chi CRLF) -> khoi phuc an toan; tra 1 = co thay doi that ->
  # giu nguyen, de `git checkout` ben duoi bao loi chu khong am tham xoa cong
  # cua ai do.
  while IFS= read -r line; do
    st="${line:0:2}"
    f="${line:3}"
    case "$st" in
      " M"|"M "|"MM")
        if git diff --quiet -- "$f" 2>/dev/null; then
          info "Khoi phuc (chi khac CRLF/LF, noi dung giong het): $f"
          git checkout -- "$f"
        else
          warn "GIU NGUYEN (co thay doi noi dung that): $f"
        fi
        ;;
    esac
  done < <(git status --porcelain)

  git checkout "$DEPLOY_REF"
  git merge --ff-only "origin/$DEPLOY_REF"
fi
NEW_HEAD=$(git rev-parse HEAD)

if [ "$DEPLOY_REF" != "main" ]; then
  echo
  warn "=============================================================="
  warn " DANG TRIEN KHAI NHANH '$DEPLOY_REF', KHONG PHAI 'main'."
  warn " https://c4-app-192.io.vn/ se phuc vu code nhanh nay cho MOI"
  warn " nguoi, ke ca ban giam khao. Day la ban TEST, khong phai release."
  warn ""
  warn " Tra ve production khi test xong:"
  warn "   DEPLOY_REF=main /opt/vivi/deploy/vps/deploy.sh"
  warn "=============================================================="
  echo
fi

if [ "$OLD_HEAD" = "$NEW_HEAD" ]; then
  ok "Da la moi nhat (${NEW_HEAD:0:7}) — khong co gi de trien khai."
  exit 0
fi
ok "Cap nhat ${OLD_HEAD:0:7} -> ${NEW_HEAD:0:7}"

echo
echo "== 3. Xac dinh phan nao thay doi =="
CHANGED=$(git diff --name-only "$OLD_HEAD" "$NEW_HEAD")

BACKEND_CHANGED=false
FRONTEND_CHANGED=false
DEPS_CHANGED=false

while IFS= read -r f; do
  case "$f" in
    src/*|requirements*.txt|Dockerfile|pyproject.toml)
      BACKEND_CHANGED=true ;;
    frontend/package.json|frontend/package-lock.json)
      FRONTEND_CHANGED=true; DEPS_CHANGED=true ;;
    frontend/src/*|frontend/public/*|frontend/*.config.*|frontend/tsconfig.json)
      FRONTEND_CHANGED=true ;;
  esac
done <<< "$CHANGED"

$BACKEND_CHANGED  && info "Backend co doi -> se rebuild"    || info "Backend khong doi -> bo qua"
$FRONTEND_CHANGED && info "Frontend co doi -> se build lai" || info "Frontend khong doi -> bo qua"

echo
echo "== 4. Backend =="
if $BACKEND_CHANGED; then
  info "docker compose build backend (co the mat vai phut)..."
  docker compose build backend
  info "docker compose up -d backend..."
  docker compose up -d backend
  ok "Backend da cap nhat va tai tao container"
else
  ok "Khong can lam gi"
fi

echo
echo "== 5. Frontend =="
if $FRONTEND_CHANGED; then
  cd "$REPO/frontend"
  if $DEPS_CHANGED; then
    info "package.json/lock doi -> npm ci..."
    npm ci
  fi
  info "npm run build..."
  npm run build
  # Chi restart SAU KHI build thanh cong (set -e da chan neu build loi) — ban
  # dang chay tiep tuc phuc vu, khong bao gio bi thay bang mot ban do dang.
  sudo systemctl restart vivi-frontend
  ok "Frontend da build lai va restart"
  cd "$REPO"
else
  ok "Khong can lam gi"
fi

echo
echo "== 6. Kiem cuoi =="

# PHAI cho, khong duoc curl mot phat. Container backend vua tai tao con phai nap
# FAISS index va model STT/TTS truoc khi probe rag_index/stt/tts bao "ready".
# Ban cu `sleep 2` + mot cu curl truot gan nhu chac chan: run 32996048723 bao
# [LOI] dung 2,8 giay sau "Container vivi-backend-1 Started", voi than phan hoi
# RONG (chua kip co HTTP response), trong khi VPS hoan toan binh thuong.
#
# `docker compose up -d --wait backend` KHONG thay duoc vong lap nay: healthcheck
# trong docker-compose.yml tro `/api/v1/status` (liveness), con readiness that la
# `/healthz` di qua Caddy.
# Chan theo THOI GIAN THAT (`SECONDS`) chu khong theo so lan lap: mot cu curl co
# the ton toi 10 giay, dem lan lap thi tran tren thanh 6 phut ma khong ai co y do.
HEALTH_DEADLINE_S=150
HEALTH_OK=false
HEALTH=""
HEALTH_TRIES=0
SECONDS=0
while :; do
  HEALTH_TRIES=$((HEALTH_TRIES + 1))
  # --max-time 10, khong phai 5: `health_probe_timeout_s` = 5 giay chan RIENG tung
  # probe (src/config.py), cong TLS va 8 component thi 5 giay la qua sat.
  HEALTH=$(curl -s --max-time 10 "https://$DOMAIN/healthz" || true)
  if echo "$HEALTH" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d['data']['status']=='ready' else 1)" 2>/dev/null; then
    HEALTH_OK=true
    ok "https://$DOMAIN/healthz -> ready (lan hoi thu $HEALTH_TRIES, sau $SECONDS giay)"
    break
  fi
  # `if` chu khong phai `[ ... ] && sleep 5`: khi phep so sanh sai, ca AND-list tra
  # 1, va mot lenh tra 1 o cuoi than vong lap se bi `set -e` giet ngay tai day.
  if [ "$SECONDS" -ge "$HEALTH_DEADLINE_S" ]; then
    break
  fi
  sleep 5
done

if ! $HEALTH_OK; then
  err "healthz KHONG ready sau $SECONDS giay ($HEALTH_TRIES lan hoi) — kiem tay:"
  echo "${HEALTH:-<curl khong tra ve gi>}"
fi

# `|| true` la BAT BUOC. Bundle sach -> `grep` khong khop -> thoat 1; voi
# `set -o pipefail` (dong 8) ca pipeline tra 1, phep gan that bai va `set -e` giet
# script dung luc moi thu deu on. Do moi la thu that su lam run 32996048723 do —
# ngu nghia bi dao nguoc: bundle sach thi job do, bundle ban (loi that) thi job xanh.
LEFTOVER=$(grep -rl "localhost:8000" "$REPO/frontend/.next/static/" 2>/dev/null | wc -l || true)
if [ "$LEFTOVER" -eq 0 ]; then
  ok "Frontend bundle sach, khong con localhost:8000"
else
  err "$LEFTOVER file bundle con troi localhost:8000 — kiem frontend/.env.production"
fi

echo
echo "== Xong: ${OLD_HEAD:0:7} -> ${NEW_HEAD:0:7} (nhanh: $DEPLOY_REF) =="

# Chot ma thoat CO CHU Y. Truoc day `err()` chi in ra chu khong exit, nen ma thoat
# cua CD khong mang thong tin gi. Tu day: do = co viec that su hong o muc 6.
if ! $HEALTH_OK || [ "$LEFTOVER" -ne 0 ]; then
  err "Code da trien khai xong nhung KIEM CUOI khong dat — xem hai muc ngay tren."
  exit 1
fi
