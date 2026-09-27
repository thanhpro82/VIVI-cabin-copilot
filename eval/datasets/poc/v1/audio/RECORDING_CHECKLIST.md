# Phase 1 domain-error recording checklist

> **Status: the corpus has already been auto-generated.**
> `scripts/synthesize_domain_audio.py` reads the table below and synthesizes all
> 24 WAV files via Piper TTS (**synthetic audio, single voice — not human
> speech**), writing `manifest.jsonl` alongside them. This file is therefore the
> **source-of-truth sentence list for that script**, and remains the reference
> for a human recording session if/when real recordings replace the synthetic
> ones. Editing a `reference_text` here changes what the script synthesizes and
> what WER/CER is scored against — re-run the script after any edit.

24 sentences, 1-2 speakers, 16kHz mono WAV each (matches the hard constraint
in `src/services/voice.py:107-121` — re-encode with any tool that can output
16-bit PCM, 16000 Hz, mono if your recorder defaults to something else).

The instructions below apply to a **human** recording pass. For the synthetic
corpus the script handles all of it (resample to 16kHz mono with anti-aliasing,
200 ms of silence padded onto each end, manifest lines written).

Record each sentence as its own WAV file under this directory (e.g.
`dom-001.wav`), then add one line per file to `manifest.jsonl` following the
schema in this directory's `README.md`. Use the `audio_id` and
`reference_text` exactly as listed below — `reference_text` is what
`word_error_rate`/`char_error_rate` will diff the transcript against, so
match it verbatim (Vietnamese diacritics included) to what was actually
spoken.

| audio_id | domain        | reference_text |
|----------|---------------|-----------------|
| dom-001  | tire_pressure | Áp suất lốp hiện tại là bao nhiêu |
| dom-002  | tire_pressure | Áp suất lốp trước bên trái là bao nhiêu |
| dom-003  | tire_pressure | Kiểm tra áp suất lốp giúp tôi |
| dom-004  | tire_pressure | Lốp sau bên phải có bị non hơi không |
| dom-005  | tire_pressure | Áp suất lốp có đang bình thường không |
| dom-006  | tire_pressure | Lốp trước có cần bơm thêm hơi không |
| dom-007  | hvac          | Bật điều hòa |
| dom-008  | hvac          | Tắt điều hòa |
| dom-009  | hvac          | Đặt điều hòa hai mươi tư độ |
| dom-010  | hvac          | Tăng nhiệt độ điều hòa lên hai mươi sáu độ |
| dom-011  | hvac          | Điều hòa đang để bao nhiêu độ |
| dom-012  | hvac          | Trong xe nóng quá, giảm điều hòa xuống |
| dom-013  | hvac          | Tôi hơi lạnh, tăng điều hòa lên một chút |
| dom-014  | hvac          | Điều hòa có đang bật không |
| dom-015  | volume        | Tăng âm lượng lên bốn mươi |
| dom-016  | volume        | Giảm âm lượng xuống hai mươi |
| dom-017  | volume        | Âm lượng hiện tại là bao nhiêu |
| dom-018  | volume        | Tắt âm lượng |
| dom-019  | volume        | Âm lượng nhạc đang to hay nhỏ |
| dom-020  | baseline      | Phát nhạc |
| dom-021  | baseline      | Mở cửa sổ bên lái |
| dom-022  | baseline      | Đóng cửa sổ bên phụ |
| dom-023  | baseline      | Bật sưởi ghế lái mức hai |
| dom-024  | baseline      | Dẫn đường đến quán cà phê gần nhất |

The `baseline` rows (dom-020..dom-024) are terms already in
`src/services/voice_correction.py`'s `COMMAND_VOCABULARY` and are expected to
transcribe reasonably today — recording them too lets the comparison show
whether Zipformer is better specifically on the *new* failing terms
(tire_pressure/hvac/volume) or uniformly across the board.
