// AudioWorkletProcessor chạy trên audio rendering thread riêng — nhận PCM
// Float32 thô từ mic (context đã tạo ở đúng 16000Hz, xem wavRecorder.ts) rồi
// chuyển từng frame về main thread qua port. Không dùng ScriptProcessorNode
// (deprecated) — bản đó bị Chrome tự "đình chỉ" xử lý sau vài giây nếu graph
// nối ra destination qua gain im lặng (cơ chế tiết kiệm pin coi graph là
// "không phát ra gì" nên tạm dừng), làm bản ghi bị cắt cụt dù overlay UI vẫn
// hiện "đang nghe" đủ thời lượng — phát hiện qua test tay thật (12s chờ tự
// dừng ra WAV chỉ ~2s âm thanh thật).
class Pcm16kRecorderProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0]?.[0];
    if (channel) {
      this.port.postMessage(channel.slice());
    }
    return true; // false sẽ khiến trình duyệt gỡ processor khỏi graph
  }
}

registerProcessor("pcm16k-recorder", Pcm16kRecorderProcessor);
