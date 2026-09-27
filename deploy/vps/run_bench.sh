#!/bin/bash
set -e
cd /opt/vivi
~/benchvenv/bin/python scripts/spike3_bench.py \
  --tag vps-e5-cpu4 \
  --model models/slm/qwen2.5-3b-instruct-q4_k_m.gguf \
  --backend cpu \
  --n 16 \
  --schema scripts/spike3_schema.json \
  --prompt-file scripts/spike3_prompt.txt
