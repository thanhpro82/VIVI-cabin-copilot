"""Hợp đồng của kênh harness `v1/sim/` — ADR-024.

**File này cố ý tách khỏi `src/models/vehicle.py`.** Ở đó là hợp đồng xe: những
thứ một chiếc xe thật cũng có. Ở đây là bàn đạo diễn kịch bản demo: "giả sử bây
giờ xe đang chạy 45 km/h" — một câu không có nghĩa với xe thật, vì trên xe thật
tốc độ do vật lý quyết định chứ không do ai ra lệnh.

Ranh giới ấy phải **nhìn thấy được**, không chỉ nằm trong đầu người viết: `rg
"v1/sim"` trả về đúng toàn bộ bề mặt harness, và mọi thứ import từ file này đều
tự khai nó thuộc bề mặt đó.

Model này được **cả hai đầu** dùng: backend validate body HTTP trước khi publish,
xe ảo validate payload nhận từ broker. Hai đầu cùng kiểm là chủ ý — route là
đường duy nhất *hôm nay*, không phải đường duy nhất mãi mãi (L2 contract test
publish thẳng vào topic, và ai cầm credential backend cũng publish được).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

#: Trần tốc độ nhận được. Không dẫn nguồn từ sổ tay VF9 — đây là trần của **bàn
#: đạo diễn**, không phải thông số xe. Đủ rộng để dựng mọi kịch bản S2/S3, đủ hẹp
#: để một lỗi đơn vị (m/s nhầm thành km/h) bị chặn thay vì publish âm thầm.
SPEED_MAX_KPH = 200.0

#: Gear hợp lệ — đúng bằng `MotionState.gear` của hợp đồng xe. Cố ý lặp lại giá
#: trị thay vì import: nếu hợp đồng xe đổi tập số thì đây phải là một quyết định
#: có người ký, không phải hệ quả trôi theo.
Gear = Literal["P", "R", "N", "D"]


class SimMotionSet(BaseModel):
    """Payload của `v1/sim/{vehicle_id}/motion/set`.

    `gear` để trống nghĩa là "chọn hộ tôi": tốc độ > 0 thì `D`, bằng 0 thì `P` —
    đúng quy ước `SimulatorRuntime.set_motion(gear=None)` mà console stdin đang
    dùng, nên `speed 45` gõ tay và thanh trượt trên màn cho cùng một kết quả.
    """

    model_config = {"extra": "forbid"}

    #: Có mặt vì mọi message trên dây trong repo này đều mang nó, và
    #: `schemas/mqtt/sim_motion_set.schema.json` đòi nó. Có default nên client
    #: HTTP không phải gửi — body `{"speed_kph": 45}` là đủ.
    schema_version: Literal["1.0"] = "1.0"
    speed_kph: float = Field(ge=0.0, le=SPEED_MAX_KPH)
    gear: Gear | None = None
