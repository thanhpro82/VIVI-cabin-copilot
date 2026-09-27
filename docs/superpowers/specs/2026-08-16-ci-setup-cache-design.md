# Thiết kế giảm thời gian setup CI

## Mục tiêu

Giảm thời gian chuẩn bị của hai workflow `CI` và `MQTT contract tests` trên
runner BTC dạng ephemeral, đồng thời vẫn chạy đúng Python 3.11.

## Nguyên nhân

Log run `31921157284` cho thấy `actions/setup-python` thiết lập Python trong
khoảng 32 giây nhưng restore pip cache 6.1 GB mất gần 8 phút. Cài dependencies
sau đó chỉ mất khoảng 50 giây. Cache hiện tại làm workflow chậm hơn đáng kể.

## Thiết kế

- Giữ `actions/setup-python@v5` và `python-version: "3.11"` để tránh phụ thuộc
  phiên bản Python ngẫu nhiên có sẵn trên runner.
- Bỏ `cache: pip` và `cache-dependency-path` khỏi cả hai workflow.
- Tiếp tục cài từ `requirements.txt` trong mỗi job. Runner ephemeral không tái sử
  dụng local cache đáng tin cậy; tải dependencies trực tiếp nhỏ hơn nhiều so với
  restore cache 6.1 GB.
- Giữ timeout CI 30 phút làm giới hạn an toàn cho runner chậm, không phải thời
  gian mục tiêu. Mục tiêu setup và install là dưới 3 phút.

## Xác minh

- Test cấu trúc workflow hiện có phải xanh.
- Run mới phải qua `Set up Python` mà không có bước `Cache restored`.
- CI fast suite và MQTT contract đều phải hoàn tất thành công.
