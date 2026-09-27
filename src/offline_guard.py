"""Chặn mọi kết nối ra ngoài loopback, và **ghi lại ai đã thử** (ADR-001).

ADR-001 nói "No network at runtime". Cho tới hôm nay đó là một tuyên bố chưa ai kiểm:
không có test nào, không có run dir nào. Module này là nửa kiểm được của nó.

## Vì sao chặn chứ không chỉ ghi

Ghi suông thì code vẫn đi ra mạng thành công và ta chỉ biết "có người gọi". Chặn thì
tái tạo đúng điều kiện của chiếc xe: mạng không có. Nhờ thế drill trả lời được câu hỏi
thật — *hệ thống có còn chạy trọn một lượt khi không có mạng không* — chứ không chỉ
"có ai gọi ra ngoài không".

## Loopback vẫn phải sống

Backend, MQTT broker, simulator và WebSocket đều nói chuyện với nhau qua 127.0.0.1.
Chặn cả loopback thì drill không đo được gì ngoài chính nó. Nên biên giới là
**loopback ↔ phần còn lại**, không phải "có socket ↔ không socket".

## Điểm mù, nói trước chứ không giấu

Cổng này vá ở tầng `socket` của Python, nên nó **không thấy** kết nối do mã native mở
thẳng qua syscall — `onnxruntime`, `faiss`, `sherpa-onnx` đều là C++. Đây không phải
lỗ hổng lý thuyết: `onnxruntime` 1.28 nạp sẵn `AzureExecutionProvider` và xếp nó
**đầu** danh sách ưu tiên trên máy này.

Vì vậy cổng Python một mình chỉ chứng minh được "không thành phần Python nào gọi ra
ngoài". Để thu hẹp phần còn lại, `ket_noi_ngoai_loopback()` hỏi thẳng hệ điều hành
xem tiến trình đang giữ kết nối nào — nó thấy cả socket do C++ mở, vì kernel không
quan tâm ai gọi. Đó là **lấy mẫu**, nên một kết nối chớp nhoáng giữa hai lần chụp vẫn
lọt; và nó vẫn không thấy giao thức không phải TCP/UDP.

Trần thật của cả hai lớp: chúng nói về **tiến trình này**. "Không byte nào rời máy"
chỉ có diễn tập ngắt card mạng thật mới trả lời được — xem `docs/offline_drill.md`.
"""

from __future__ import annotations

import socket
import traceback
from dataclasses import dataclass, field

#: Địa chỉ được phép. `0.0.0.0` nằm đây vì `bind()` dùng nó để nghe mọi giao diện —
#: nghe không phải là gọi ra ngoài.
_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost", "0.0.0.0", "", "::"})


def _la_loopback(host: object) -> bool:
    if not isinstance(host, str):
        return False
    ten = host.strip("[]").lower()
    return ten in _LOOPBACK or ten.startswith("127.")


@dataclass(frozen=True)
class LanThu:
    """Một lần thử đi ra ngoài, kèm chỗ gọi."""

    kieu: str  # "connect" | "getaddrinfo"
    dich: str
    stack: str

    def goi_tu(self) -> str:
        """Khung ngoài cùng thuộc về `src/` — thứ duy nhất đáng đưa vào báo cáo."""
        for dong in reversed(self.stack.splitlines()):
            if "site-packages" in dong or "offline_guard" in dong:
                continue
            if dong.strip().startswith("File ") and ("\\src\\" in dong or "/src/" in dong):
                return dong.strip()
        return "(không xác định)"


class ChanMangError(OSError):
    """Cùng họ `OSError` với lỗi mạng thật, nên code fail-open bắt được như thường.

    Cố ý **không** dùng exception riêng: nếu drill ném ra một loại lỗi mà production
    không bao giờ thấy, ta đo hành vi của một hệ thống khác với hệ thống thật.
    """


def ket_noi_ngoai_loopback() -> list[str]:
    """Hỏi HĐH: tiến trình này đang giữ kết nối nào ra ngoài loopback?

    Bổ sung cho cổng Python chứ không thay thế. Cổng biết **ai gọi** nhưng mù với mã
    native; lớp này thấy cả C++ nhưng không biết ai gọi. Cần cả hai.

    Trả danh sách rỗng nếu không quan sát được (thiếu `psutil`, hoặc HĐH từ chối) —
    **không** ném lỗi, vì "không đo được" không phải "đã đo và sạch". Người gọi phân
    biệt hai ca ấy bằng `quan_sat_duoc_ket_noi()`.
    """
    if not quan_sat_duoc_ket_noi():
        return []
    import psutil

    ra_ngoai: list[str] = []
    try:
        for ket_noi in psutil.Process().net_connections(kind="inet"):
            xa = ket_noi.raddr
            if xa and not _la_loopback(getattr(xa, "ip", None)):
                ra_ngoai.append(f"{xa.ip}:{xa.port} ({ket_noi.status})")
    except (psutil.Error, OSError):
        return []
    return sorted(set(ra_ngoai))


def quan_sat_duoc_ket_noi() -> bool:
    """`psutil` có mặt và đọc được bảng kết nối của chính tiến trình này không."""
    try:
        import psutil

        psutil.Process().net_connections(kind="inet")
    except Exception:  # noqa: BLE001 — thiếu quyền, thiếu gói, HĐH lạ: đều là "không đo được"
        return False
    return True


@dataclass
class CongChanEgress:
    """Vá `socket` trong tiến trình hiện tại. Dùng như context manager."""

    lan_thu: list[LanThu] = field(default_factory=list)
    _goc: dict = field(default_factory=dict, repr=False)

    def _ghi(self, kieu: str, dich: str) -> None:
        self.lan_thu.append(LanThu(kieu=kieu, dich=dich, stack="".join(traceback.format_stack()[:-2])))

    def __enter__(self) -> CongChanEgress:
        self._goc = {
            "connect": socket.socket.connect,
            "connect_ex": socket.socket.connect_ex,
            "create_connection": socket.create_connection,
            "getaddrinfo": socket.getaddrinfo,
        }
        cong = self

        def _kiem_dia_chi(address: object) -> None:
            host = address[0] if isinstance(address, tuple) and address else address
            if _la_loopback(host):
                return
            cong._ghi("connect", str(host))
            raise ChanMangError(101, f"diễn tập offline chặn kết nối ra {host!r}")

        def connect(self_sock, address):  # noqa: ANN001
            _kiem_dia_chi(address)
            return cong._goc["connect"](self_sock, address)

        def connect_ex(self_sock, address):  # noqa: ANN001
            _kiem_dia_chi(address)
            return cong._goc["connect_ex"](self_sock, address)

        def create_connection(address, *args, **kwargs):  # noqa: ANN001
            _kiem_dia_chi(address)
            return cong._goc["create_connection"](address, *args, **kwargs)

        def getaddrinfo(host, port, *args, **kwargs):  # noqa: ANN001
            # DNS là tín hiệu **sớm nhất** và rõ nhất: một tên miền cần phân giải nghĩa
            # là ai đó định gọi ra ngoài, kể cả khi kết nối chưa xảy ra.
            if not _la_loopback(host):
                cong._ghi("getaddrinfo", str(host))
                raise socket.gaierror(-2, f"diễn tập offline chặn phân giải tên {host!r}")
            return cong._goc["getaddrinfo"](host, port, *args, **kwargs)

        socket.socket.connect = connect
        socket.socket.connect_ex = connect_ex
        socket.create_connection = create_connection
        socket.getaddrinfo = getaddrinfo
        return self

    def __exit__(self, *_exc) -> None:
        socket.socket.connect = self._goc["connect"]
        socket.socket.connect_ex = self._goc["connect_ex"]
        socket.create_connection = self._goc["create_connection"]
        socket.getaddrinfo = self._goc["getaddrinfo"]
        self._goc.clear()
