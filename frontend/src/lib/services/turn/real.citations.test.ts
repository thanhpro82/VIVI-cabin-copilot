/**
 * `assistant.response` phải được **ánh xạ**, không phải ép kiểu.
 *
 * Bug thật, người dùng gặp khi test tay 15/08: góc màn hình hiện "Each child in a list
 * should have a unique key prop — CitationList.tsx (49:13)", dù dòng 49 đã có
 * `key={citation.citationId}`. React cảnh báo vì key là `undefined` cho **mọi** phần
 * tử, không phải vì thiếu key.
 *
 * Nguyên nhân: `real.ts` viết `p.citations as Citation[]`. `as` là khẳng định lúc biên
 * dịch, không sinh mã — nên lúc chạy mỗi phần tử vẫn mang `citation_id` của backend.
 *
 * Payload trong file này chép **nguyên văn** từ `assistant_response_payload`
 * (`src/services/ivi_events.py:250`), chứ không viết lại theo trí nhớ: nếu nó khớp một
 * hình dạng tưởng tượng thì test xanh mà FE vẫn hỏng — đúng cách bug này lọt lần đầu.
 */
import { describe, expect, it } from "vitest";

import { mapServerEvent } from "./real";

/** Nguyên văn payload backend cho câu hỏi áp suất lốp (đo trên backend thật 15/08). */
const RAW = {
  type: "assistant.response",
  turn_id: "trn_abc123",
  payload: {
    display_text: "Đây là thông tin tôi tìm được trong sổ tay xe.",
    speak_text: "Đây là thông tin tôi tìm được trong sổ tay xe.",
    has_more_to_read: true,
    citations: [
      {
        citation_id: "cit_04e418ee0ccc",
        document_title: "Sổ tay VF9",
        section: "Áp suất lốp",
        page: 2,
        excerpt: "Tất cả các áp suất lốp...",
        retrieval_score: 0.91,
      },
      {
        citation_id: "cit_f709c5c336c6",
        document_title: "Sổ tay VF9",
        section: "Vành và bánh xe",
        page: 5,
        excerpt: "Thông số kỹ thuật lốp xe...",
        retrieval_score: 0.88,
      },
    ],
    outcomes: [{ step_id: "stp_1", status: "succeeded" }],
  },
};

describe("mapServerEvent — assistant.response", () => {
  it("đọc citation_id thành citationId thay vì để undefined", () => {
    const event = mapServerEvent(RAW);

    expect(event?.type).toBe("assistant.response");
    const citations = event!.type === "assistant.response" ? event.result.citations : [];
    expect(citations.map((c) => c.citationId)).toEqual(["cit_04e418ee0ccc", "cit_f709c5c336c6"]);
    expect(citations.map((c) => c.documentTitle)).toEqual(["Sổ tay VF9", "Sổ tay VF9"]);
  });

  it("giữ nguyên ba trường vốn trùng tên ở hai bên", () => {
    // `section`, `page`, `excerpt` giống nhau ở cả snake_case lẫn camelCase, nên chúng
    // vẫn hiện đúng kể cả khi ép kiểu — và chính điều đó làm bug khó thấy. Chốt lại để
    // bản sửa không vô tình làm hỏng phần đang chạy được.
    const event = mapServerEvent(RAW);
    const citations = event!.type === "assistant.response" ? event.result.citations : [];
    expect(citations[0]).toMatchObject({ section: "Áp suất lốp", page: 2, excerpt: "Tất cả các áp suất lốp..." });
  });

  it("key của mỗi citation là duy nhất và không rỗng", () => {
    // Đây đúng là bất biến React đòi hỏi ở `<li key=...>`. Kiểm thẳng nó thay vì kiểm
    // gián tiếp qua render, để lỗi báo ở tầng dữ liệu — nơi nó thật sự nằm.
    const event = mapServerEvent(RAW);
    const citations = event!.type === "assistant.response" ? event.result.citations : [];
    const keys = citations.map((c) => c.citationId);

    expect(keys.every((k) => typeof k === "string" && k.length > 0)).toBe(true);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("đọc step_id thành stepId — cùng lỗi ép kiểu, cùng một dòng", () => {
    const event = mapServerEvent(RAW);
    const outcomes = event!.type === "assistant.response" ? event.result.outcomes : [];
    expect(outcomes).toEqual([{ stepId: "stp_1", status: "succeeded" }]);
  });

  /**
   * `has_more_to_read` là cờ điều khiển nút "Nghe tiếp" (issue #116). Backend
   * chưa gửi nó trên develop (PR #108 chưa merge), nên hành vi khi THIẾU field
   * mới là thứ chạy thật hôm nay — và nó phải là "không có nút", không phải một
   * nút dẫn tới ngõ cụt.
   */
  it("đọc has_more_to_read khi backend gửi", () => {
    const event = mapServerEvent(RAW);
    const result = event!.type === "assistant.response" ? event.result : null;
    expect(result?.hasMoreToRead).toBe(true);
  });

  it("thiếu has_more_to_read thì là false, không phải undefined", () => {
    const event = mapServerEvent({
      type: "assistant.response",
      turn_id: "trn_x",
      payload: { display_text: "Đã thực hiện.", speak_text: "Đã thực hiện." },
    });
    const result = event!.type === "assistant.response" ? event.result : null;

    expect(result?.hasMoreToRead).toBe(false);
  });

  it("giá trị lạ (chuỗi, số) không được hiểu thành 'còn nữa'", () => {
    // `as boolean` sẽ để "false" (chuỗi) lọt qua thành truthy. `=== true` thì không.
    for (const weird of ["false", "true", 1, 0, null]) {
      const event = mapServerEvent({
        type: "assistant.response",
        turn_id: "trn_x",
        payload: { display_text: "x", speak_text: "x", has_more_to_read: weird },
      });
      const result = event!.type === "assistant.response" ? event.result : null;
      expect(result?.hasMoreToRead).toBe(false);
    }
  });

  it("không vỡ khi backend không gửi citations", () => {
    // Lượt điều khiển ("bật điều hoà") không có citation nào. Trước đây `?? []` lo việc
    // này; bản ánh xạ phải giữ đúng hành vi ấy.
    const event = mapServerEvent({
      type: "assistant.response",
      turn_id: "trn_x",
      payload: { display_text: "Đã thực hiện.", speak_text: "Đã thực hiện." },
    });
    const result = event!.type === "assistant.response" ? event.result : null;
    expect(result?.citations).toEqual([]);
    expect(result?.outcomes).toEqual([]);
  });
});
