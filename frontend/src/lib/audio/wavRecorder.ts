/**
 * Ghi âm mic thật → WAV 16-bit PCM mono 16kHz, encode ngay trong trình duyệt.
 *
 * KHÔNG dùng `MediaRecorder` — nó chỉ ghi ra container nén (webm/opus ở
 * Chrome/Firefox, mp4/aac ở Safari), không có browser nào ghi thẳng ra WAV.
 * Backend (`src/services/voice.py::_validate_audio`) đòi ĐÚNG 16kHz mono —
 * lệch sample rate (mặc định AudioContext thường là 44.1kHz/48kHz theo phần
 * cứng) bị từ chối thẳng với `"audio must be 16kHz mono WAV"`, không phải lỗi
 * định dạng container như mô tả ở CLAUDE.md mục "STT accepts only WAV" (đấy
 * là lớp khác — sai container hoàn toàn; đây là đúng container, sai tốc độ
 * lấy mẫu). Xin thẳng `AudioContext` ở 16000Hz (`sampleRate` trong
 * constructor options, Chrome/Firefox/Safari hiện đại đều theo) để khỏi phải
 * tự viết resampler; `resampleLinear()` bên dưới chỉ là lưới an toàn cho
 * trường hợp hiếm trình duyệt ghim cứng theo sample rate phần cứng và lờ đi
 * option này.
 *
 * Dùng `AudioWorkletNode` (`public/worklets/pcm16k-recorder.js`), KHÔNG dùng
 * `ScriptProcessorNode` — bản đầu dùng ScriptProcessorNode vì không cần thêm
 * asset tĩnh, nhưng test tay thật lộ ra bug nghiêm trọng: Chrome tự "đình
 * chỉ" xử lý ScriptProcessorNode sau khoảng ~2 giây nếu graph nối ra
 * destination qua gain im lặng (chủ đích để không phát tiếng mic ra loa) —
 * cơ chế tiết kiệm pin coi graph "không phát ra âm thanh nghe được" nên tạm
 * dừng, cắt cụt bản ghi dù overlay UI vẫn hiện "đang nghe" đủ 12 giây.
 * `AudioWorkletNode` chạy trên audio rendering thread riêng, không thuộc
 * nhóm node cũ bị áp cơ chế đình chỉ này.
 */

export interface WavRecording {
  /** Dừng ghi, đợi nốt buffer cuối cùng từ worklet rồi trả về WAV Blob. */
  stop(): Promise<Blob>;
  /** Dừng ghi, không cần Blob — dọn mic/AudioContext khi người dùng huỷ giữa chừng. */
  cancel(): void;
  /** True nếu đã có ít nhất 1 đoạn năng lượng vượt ngưỡng giọng nói — phân biệt "ghi được câu ngắn" khỏi "im lặng/ồn nền suốt". */
  hadSpeech(): boolean;
}

export interface StartWavRecordingOptions {
  /**
   * Gọi ĐÚNG 1 LẦN khi phát hiện im lặng liên tục đủ lâu SAU KHI đã có giọng
   * nói — nơi gọi (DriverShellProvider) tự quyết định dừng ghi thật (thường
   * là gọi `stop()`), hàm này không tự dừng gì cả, chỉ báo hiệu. Không truyền
   * thì tắt hẳn VAD — ghi tiếp tới khi bị dừng thủ công/timeout ngoài.
   */
  onSilenceDetected?: () => void;
  /**
   * Gọi mỗi khối PCM với mức 0..1, cho UI phản ứng theo âm lượng thật (issue
   * #342) — chuẩn hoá theo đỉnh RMS đã thấy trong CHÍNH lượt ghi này, không
   * phải một thang tuyệt đối cố định, cùng cách tiếp cận với đường wake word
   * (`WakeWordController.observeCaptureFrame`).
   */
  onLevel?: (level: number) => void;
}

const TARGET_SAMPLE_RATE = 16000;
const WORKLET_URL = "/worklets/pcm16k-recorder.js";
const WORKLET_NAME = "pcm16k-recorder";
/** Đợi message cuối từ worklet sau khi ngắt nguồn — postMessage tới main thread thường về trong 1 task, 80ms rộng rãi. */
const FLUSH_DELAY_MS = 80;

/**
 * Ngưỡng RMS (root-mean-square) coi là "có giọng nói" trên PCM Float32
 * chuẩn hoá [-1, 1] — chọn tay qua vài lần test nói/im lặng thật, không phải
 * số đo khoa học; nhiễu nền phòng bình thường thường dưới ~0.01. Đặt ở đây,
 * không phải trong worklet, vì tính toán rẻ (một vòng lặp cộng bình phương
 * trên block 128 mẫu) — không đáng để chuyển sang audio rendering thread
 * riêng như việc encode/ghi buffer.
 */
const SILENCE_RMS_THRESHOLD = 0.02;
/** Im lặng liên tục bao lâu SAU KHI đã có giọng nói thì coi là "nói xong". */
const SILENCE_DURATION_MS = 900;

function computeRms(samples: Float32Array): number {
  let sumSquares = 0;
  for (let i = 0; i < samples.length; i++) sumSquares += samples[i] * samples[i];
  return Math.sqrt(sumSquares / samples.length);
}

/**
 * Theo dõi năng lượng audio để (a) biết đã có giọng nói thật chưa
 * (`hadSpeech()`, dùng bất kể có bật VAD hay không — trước đây gộp chung
 * điều kiện với VAD nên KHÔNG truyền `onSilenceDetected` thì `hadSpeech()`
 * luôn trả `false` dù có nói thật, một bug tiềm ẩn chưa ai gặp vì
 * `DriverShellProvider` hiện luôn truyền callback) và (b) tự báo khi im lặng
 * đủ lâu sau khi đã nói (VAD, tuỳ chọn). Tách khỏi `startWavRecording()` để
 * test được thuần bằng dữ liệu PCM giả, không cần giả lập AudioContext/
 * AudioWorkletNode (jsdom không có Web Audio API thật).
 */
export function createSpeechEnergyTracker(onSilenceDetected?: () => void, onLevel?: (level: number) => void) {
  let hasSpeech = false;
  let silenceMs = 0;
  let fired = false;
  let peakRms = 0;

  return {
    /** Cho 1 khối PCM Float32 + độ dài của nó tính bằng mili-giây. */
    feed(chunk: Float32Array, chunkMs: number): void {
      const rms = computeRms(chunk);
      if (rms >= SILENCE_RMS_THRESHOLD) {
        hasSpeech = true;
        silenceMs = 0;
        peakRms = Math.max(peakRms, rms);
        onLevel?.(peakRms > 0 ? Math.min(1, rms / peakRms) : 0);
        return;
      }
      onLevel?.(peakRms > 0 ? Math.min(1, rms / peakRms) : 0);
      // Chỉ BẮT ĐẦU đếm im lặng SAU KHI đã có giọng nói thật, tránh tự cắt
      // ngay khi vừa mở overlay mà người dùng chưa kịp nói gì (im lặng "chưa
      // nói" khác im lặng "nói xong rồi").
      if (!hasSpeech || fired || !onSilenceDetected) return;
      silenceMs += chunkMs;
      if (silenceMs >= SILENCE_DURATION_MS) {
        fired = true;
        onSilenceDetected();
      }
    },
    hadSpeech: () => hasSpeech,
  };
}

/** Nội suy tuyến tính đơn giản — chỉ chạy khi trình duyệt lờ đi `sampleRate` đã xin. */
function resampleLinear(input: Float32Array, fromRate: number, toRate: number): Float32Array {
  if (fromRate === toRate) return input;
  const ratio = fromRate / toRate;
  const outLength = Math.round(input.length / ratio);
  const output = new Float32Array(outLength);
  for (let i = 0; i < outLength; i++) {
    const srcPos = i * ratio;
    const srcIndex = Math.floor(srcPos);
    const frac = srcPos - srcIndex;
    const a = input[srcIndex] ?? 0;
    const b = input[srcIndex + 1] ?? a;
    output[i] = a + (b - a) * frac;
  }
  return output;
}

function encodeWav(chunks: Float32Array[], sourceSampleRate: number): Blob {
  const capturedTotal = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const merged = new Float32Array(capturedTotal);
  let mergedOffset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, mergedOffset);
    mergedOffset += chunk.length;
  }
  // Lưới an toàn: sourceSampleRate lẽ ra đã là 16000 vì xin thẳng trong
  // constructor, nhưng vài engine vẫn ghim theo phần cứng — resample về đúng
  // backend đòi thay vì gửi lên rồi bị 400 "audio must be 16kHz mono".
  const samples =
    sourceSampleRate === TARGET_SAMPLE_RATE ? merged : resampleLinear(merged, sourceSampleRate, TARGET_SAMPLE_RATE);

  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);

  function writeString(offset: number, text: string) {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
  }

  writeString(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, TARGET_SAMPLE_RATE, true);
  view.setUint32(28, TARGET_SAMPLE_RATE * 2, true); // byte rate: mono * 16-bit
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  writeString(36, "data");
  view.setUint32(40, samples.length * 2, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i++, offset += 2) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  }

  return new Blob([buffer], { type: "audio/wav" });
}

export async function startWavRecording(options: StartWavRecordingOptions = {}): Promise<WavRecording> {
  const { onSilenceDetected, onLevel } = options;
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const AudioContextCtor = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  const audioContext = new AudioContextCtor({ sampleRate: TARGET_SAMPLE_RATE });
  await audioContext.audioWorklet.addModule(WORKLET_URL);

  const source = audioContext.createMediaStreamSource(stream);
  const workletNode = new AudioWorkletNode(audioContext, WORKLET_NAME);
  const chunks: Float32Array[] = [];
  let stopped = false;
  const speechTracker = createSpeechEnergyTracker(onSilenceDetected, onLevel);

  workletNode.port.onmessage = (event: MessageEvent<Float32Array>) => {
    if (stopped) return;
    const chunk = event.data;
    chunks.push(chunk);
    speechTracker.feed(chunk, (chunk.length / audioContext.sampleRate) * 1000);
  };

  // Vẫn nối ra destination qua gain 0 (không phát tiếng mic ra loa) — khác
  // ScriptProcessorNode, AudioWorkletNode không cần đường này để giữ
  // `process()` chạy, nhưng giữ lại cho nhất quán và phòng engine hiếm cần.
  const silentGain = audioContext.createGain();
  silentGain.gain.value = 0;
  source.connect(workletNode);
  workletNode.connect(silentGain);
  silentGain.connect(audioContext.destination);

  function disconnectGraph() {
    workletNode.port.onmessage = null;
    workletNode.disconnect();
    source.disconnect();
    silentGain.disconnect();
  }

  function teardown() {
    if (stopped) return;
    stopped = true;
    disconnectGraph();
    for (const track of stream.getTracks()) track.stop();
    void audioContext.close();
  }

  return {
    async stop() {
      if (stopped) return encodeWav(chunks, audioContext.sampleRate);
      // Ngắt nguồn trước để worklet ngừng sinh message mới, rồi đợi ngắn để
      // nhận nốt message cuối đã gửi trước khi ngắt (postMessage không đồng
      // bộ với việc disconnect).
      source.disconnect();
      await new Promise((resolve) => setTimeout(resolve, FLUSH_DELAY_MS));
      const blob = encodeWav(chunks, audioContext.sampleRate);
      teardown();
      return blob;
    },
    cancel: teardown,
    hadSpeech: speechTracker.hadSpeech,
  };
}
