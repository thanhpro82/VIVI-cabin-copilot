/**
 * Ghi âm từ một `MicrophonePipeline` ĐANG chạy, không mở thêm micro thứ hai.
 *
 * Tách khỏi `wavRecorder.ts` có chủ ý: đường chạm-mic của `wavRecorder` đã có
 * nhiều bản sửa vòng đời micro (mic lượt phê duyệt, ba lỗ im lặng, hẹn giờ hết
 * hạn) và không có lý do gì để nó phải đổi khi wake word xuất hiện. Wake word
 * dùng đồ thị âm thanh riêng của nó; hai bên chỉ chia nhau kiểu `WavRecording`.
 */

import { MicrophonePipeline } from "./microphonePipeline";
import { PCM_SAMPLE_RATE, createSpeechEnergyTracker, encodePcm16Wav } from "./pcm";
import type { WavRecording } from "./wavRecorder";

export type { WavRecording } from "./wavRecorder";

export interface PipelineRecordingOptions {
  onSilenceDetected?: () => void;
  initialPcm?: Float32Array | readonly number[];
  /**
   * Chỉ nhận khung có `sequence` LỚN HƠN mốc này. Đây là thứ ngăn âm thanh của
   * chính câu đánh thức lọt vào bản ghi câu lệnh — bộ đệm bảo vệ giữ lại phần
   * ngay trước mốc, nhưng những khung đã dùng để nhận ra "Hey Vi Vi" thì không
   * được gửi lên backend.
   */
  afterSequence: number;
}

export function createPipelineRecording(
  pipeline: MicrophonePipeline,
  { initialPcm = [], afterSequence, onSilenceDetected }: PipelineRecordingOptions,
): WavRecording {
  const initialChunk = Float32Array.from(initialPcm);
  const chunks = initialChunk.length > 0 ? [initialChunk] : [];
  let stopped = false;
  const speechTracker = createSpeechEnergyTracker(onSilenceDetected);
  if (initialChunk.length > 0) {
    speechTracker.feed(initialChunk, (initialChunk.length / PCM_SAMPLE_RATE) * 1000);
  }

  const subscription = pipeline.subscribe((frame) => {
    if (stopped) return;
    if (frame.sequence <= afterSequence) return;
    const chunk = frame.samples.slice();
    chunks.push(chunk);
    speechTracker.feed(chunk, (chunk.length / PCM_SAMPLE_RATE) * 1000);
  });

  function teardown() {
    if (stopped) return;
    stopped = true;
    subscription.unsubscribe();
  }

  return {
    async stop() {
      teardown();
      return encodePcm16Wav(chunks, PCM_SAMPLE_RATE);
    },
    cancel: teardown,
    hadSpeech: speechTracker.hadSpeech,
  };
}
