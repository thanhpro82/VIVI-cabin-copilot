# ---- Stage 1: Build ----
FROM python:3.11-slim AS builder

WORKDIR /app

# HF_HOME dat tuong minh, KHONG dua vao mac dinh ~/.cache/huggingface: stage nay
# chay bang root con stage sau chay bang appuser, hai $HOME khac nhau nen cache
# tai o day se nam ngoai duong tim cua runtime. Tro ca hai stage vao cung mot
# duong tuyet doi.
ENV HF_HOME=/opt/hf

COPY requirements.txt requirements-rag.txt requirements-voice.txt ./

# torch phai cai tu index CPU-only TRUOC sentence-transformers. Ban torch mac
# dinh tren PyPI keo theo toan bo runtime CUDA (~2,5 GB) — vo dung tren VPS
# khong GPU va lam image phinh gap may lan. Cai truoc de sentence-transformers
# thay torch da thoa va khong keo ban CUDA ve nua.
RUN pip install --no-cache-dir --user --index-url https://download.pytorch.org/whl/cpu torch

# Ba file, ba muc dich: requirements.txt = loi (CI cung cai dung file nay),
# requirements-rag.txt = embedder that, requirements-voice.txt = STT/TTS that.
RUN pip install --no-cache-dir --user \
      -r requirements.txt \
      -r requirements-rag.txt \
      -r requirements-voice.txt

# Nap san multilingual-e5-small vao image. BAT BUOC, khong phai toi uu:
# src/rag/embed.py:112 dat `local_files_only=True` nen luc chay no khong bao gio
# tu tai — thieu cache la nem loi ngay o luot tra so tay dau tien. Ghim revision
# theo dung ky luat artifact cua docs/devops.md ("pinned source/revision").
# License MIT.
#
# `allow_patterns` liet ke tay tung file, KHONG dung glob kieu "*.json": repo nay
# co san cung mot model o BON dinh dang (safetensors, pytorch_model.bin, onnx/,
# openvino/) va sentence-transformers chi doc dung ban safetensors. Tai het la
# 2154 MB thay vi 472 MB — do bang `du` trong container, run
# eval/results/resource-footprint/20260818T141151.483598Z. Va khong dung glob duoc
# vi `fnmatch` trong huggingface_hub coi `*` khop ca dau `/`, nen "*.json" van keo
# theo `onnx/config.json` roi keo theo ca thu muc onnx.
ARG E5_REVISION=614241f622f53c4eeff9890bdc4f31cfecc418b3
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('intfloat/multilingual-e5-small', revision='${E5_REVISION}', allow_patterns=['config.json','model.safetensors','modules.json','sentence_bert_config.json','sentencepiece.bpe.model','special_tokens_map.json','tokenizer.json','tokenizer_config.json','1_Pooling/config.json'])"

# Viet tay `refs/main`. Day la cho lam RAG chet cam tren container ma van bao
# healthy: `snapshot_download(revision=<sha>)` chi tao `snapshots/<sha>/`, KHONG
# tao `refs/`. Luc chay, `SentenceTransformer('intfloat/multilingual-e5-small')`
# khong truyen revision nen huggingface_hub phan giai revision mac dinh `main`,
# di tim `refs/main`, khong thay, roi goi ra huggingface.co — ma
# `local_files_only=True` cam dieu do. Ket qua: moi cau tra so tay tra ve "Toi
# khong tim thay thong tin nay trong so tay xe.", healthcheck van xanh, va 472 MB
# cache nam trong image khong ai dung toi.
#
# Van giu revision ghim: file nay chi tro ten `main` ve dung sha da ghim o tren,
# khong noi long ky luat artifact.
RUN mkdir -p /opt/hf/hub/models--intfloat--multilingual-e5-small/refs \
    && printf '%s' "${E5_REVISION}" > /opt/hf/hub/models--intfloat--multilingual-e5-small/refs/main

# Chot chan luc BUILD, cung kieu voi chot chan artifact voice o stage sau. Loi
# `refs/main` ton tai duoc la vi khong co gi kiem tra cache co dung duoc hay
# khong — bo test 1356 case khong bat duoc, vi chung chay trong process voi cache
# cua may dev. Dong duoi day nap model y het luc runtime (offline, local-only);
# hong la build do ngay, khong doi toi giua buoi demo.
RUN HF_HUB_OFFLINE=1 python -c "from sentence_transformers import SentenceTransformer; m = SentenceTransformer('intfloat/multilingual-e5-small', local_files_only=True); print('E5 nap offline OK, dim =', m.get_sentence_embedding_dimension())"

# ---- Stage 2: Production ----
FROM python:3.11-slim

WORKDIR /app

ENV HF_HOME=/opt/hf

# Security: run as non-root user. Tao TRUOC khi COPY de `--chown` co user that.
RUN useradd -m appuser

# Copy installed packages from builder.
#
# Phai vao /home/appuser/.local, KHONG phai /root/.local. `pip install --user` o
# stage build dat goi vao /root/.local, nhung container chay bang `appuser` nen
# Python chi tim user site-packages tai $HOME/.local — va /root con mode 700 nen
# appuser khong doc noi. Ban truoc copy sang /root/.local roi chi them
# `ENV PATH=/root/.local/bin`, ma PATH chi anh huong duong tim BINARY, khong them
# duong import; ket qua la container chet ngay dong import dau tien voi
# `ModuleNotFoundError: No module named 'pydantic'` va restart vo han.
# Kiem chung: `docker run --rm <image> python -c "import sys; print(sys.path)"`
# khong he co thu muc .local nao.
COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local
COPY --from=builder --chown=appuser:appuser /opt/hf /opt/hf
ENV PATH=/home/appuser/.local/bin:$PATH

# Copy application code
COPY --chown=appuser:appuser . .

# Chot chan artifact voice. `models/voice/*` nam trong .gitignore nen `git clone`
# KHONG mang model theo, trong khi .dockerignore lai khong loai thu muc do — hau
# qua la cung mot lenh `docker compose build` cho hai ket qua: tren may da co
# model thi ra image day du, tren may vua clone thi ra image THIEU STT/TTS ma
# van build xanh, van chay, van bao healthy. Loi chi lo ra khi co nguoi bam micro
# giua buoi demo, vi sherpa_onnx/piper deu duoc import lazy.
# Fail o day, luc build, thay vi o do.
RUN set -e; \
    for f in models/voice/vi_VN-piper.onnx \
             models/voice/vi_VN-piper.onnx.json \
             models/voice/zipformer-30m-rnnt-6000h/encoder.int8.onnx \
             models/voice/zipformer-30m-rnnt-6000h/decoder.int8.onnx \
             models/voice/zipformer-30m-rnnt-6000h/joiner.int8.onnx \
             models/voice/zipformer-30m-rnnt-6000h/tokens.txt; do \
      if [ ! -f "$f" ]; then \
        echo "THIEU ARTIFACT VOICE: $f"; \
        echo "Model khong nam trong git (.gitignore). Chay scripts/setup_voice_models.ps1"; \
        echo "hoac copy thu muc models/voice/ vao build context truoc khi build."; \
        exit 1; \
      fi; \
    done

# Index RAG chi canh bao, khong fail: docker-compose.yml bind-mount `./data` de
# len /app/data, nen ban trong image bi che khuat va cai thuc su duoc dung la
# thu muc data/ tren host. Ban image chi co tac dung khi chay `docker run` tran.
RUN if [ ! -f data/rag/vf9_2026_vi/index.faiss ]; then \
      echo "CANH BAO: khong thay data/rag/vf9_2026_vi/index.faiss trong build context."; \
      echo "Voi docker compose thi khong sao (data/ duoc bind-mount tu host),"; \
      echo "nhung host BAT BUOC phai co thu muc do — no cung nam ngoai git."; \
    fi

# Create data directory with correct ownership
RUN mkdir -p /app/data && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/status')" || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
