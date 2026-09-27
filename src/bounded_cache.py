"""Cache LRU có trần, dùng cho các bảng idempotency.

Simulator và executor đều phải nhớ kết quả theo `command_id` /
`idempotency_key` để duplicate delivery của QoS 1 không tạo transition thứ
hai. Nhớ bằng `dict` trần thì bảng phình vô hạn: process chạy lâu tích luỹ
mọi lệnh từng nhận. Đây là cùng một bảng đó nhưng có trần.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")

#: Đủ lớn để một phiên demo không bao giờ chạm tới, đủ nhỏ để không phình.
DEFAULT_MAXSIZE = 1024


class BoundedCache(Generic[K, V]):
    """LRU đơn giản: đọc trúng thì đẩy lên mới nhất, quá trần thì bỏ cũ nhất.

    Không dùng `functools.lru_cache` vì ta cần ghi giá trị vào theo key chứ
    không phải nhớ kết quả của một hàm thuần.
    """

    def __init__(self, maxsize: int = DEFAULT_MAXSIZE) -> None:
        if maxsize < 1:
            raise ValueError("maxsize phải >= 1")
        self._maxsize = maxsize
        self._items: OrderedDict[K, V] = OrderedDict()

    @property
    def maxsize(self) -> int:
        return self._maxsize

    def get(self, key: K) -> V | None:
        value = self._items.get(key)
        if value is not None:
            self._items.move_to_end(key)
        return value

    def set(self, key: K, value: V) -> None:
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self._maxsize:
            self._items.popitem(last=False)

    def values(self) -> list[V]:
        """Ảnh chụp mọi giá trị, cũ nhất trước.

        Trả `list` chứ không phải view của `OrderedDict`: người gọi thường lặp rồi
        lọc, mà `get()` lại `move_to_end` — lặp trên view sống trong khi có ai đó
        đọc cache sẽ ném `RuntimeError: OrderedDict mutated during iteration`.
        """
        return list(self._items.values())

    def __contains__(self, key: object) -> bool:
        return key in self._items

    def __len__(self) -> int:
        return len(self._items)
