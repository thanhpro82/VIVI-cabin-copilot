"""Entrypoint xe ảo: `python -m src.vehicle_sim`.

Chạy như một process riêng, không public port — theo docs/technical_spec.md.

Khi chạy trong terminal, đọc thêm lệnh điều khiển chuyển động từ stdin:

    speed 45        # 45 km/h, tự chuyển số D
    speed 45 D      # nói rõ số
    gear P          # đổi số, giữ nguyên tốc độ
    stop            # về 0 km/h, số P
    state           # in tốc độ/số/version hiện tại

Đây là cách **duy nhất hợp lệ** để cho xe chạy phục vụ demo S3 (chặn mở cửa khi
đang di chuyển): `motion` là read-only domain nên không có topic lệnh, và ACL cấm
backend publish `state/*`. Xe tự đặt tốc độ của chính nó thì không vi phạm gì.
Xem ADR-013.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys

from src.config import get_settings
from src.services.mqtt_client import AiomqttClient, ensure_selector_event_loop
from src.vehicle_sim.runtime import SimulatorRuntime, will_for
from src.vehicle_sim.state import VehicleSimulator

logger = logging.getLogger(__name__)

# Console in tiếng Việt. Khi stdout là console thì Windows dùng UTF-8, nhưng khi
# nó là pipe (`| tee log.txt`, `docker logs`, subprocess) thì Python rơi về
# cp1252 và mọi dấu tiếng Việt giết tiến trình bằng UnicodeEncodeError — tức xe
# ảo chết đúng lúc ai đó thu log lại.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_HELP = "lệnh: speed <km/h> [gear] | gear <P|R|N|D> | stop | state | help"


async def _apply_console_command(runtime: SimulatorRuntime, line: str) -> None:
    """Diễn giải một dòng lệnh. Sai cú pháp thì in hướng dẫn, không làm chết loop."""
    parts = line.split()
    if not parts:
        return
    verb, args = parts[0].lower(), parts[1:]
    motion = runtime.simulator.state.motion

    if verb in {"help", "?"}:
        print(_HELP)
    elif verb == "state":
        print(f"speed={motion.speed_kph} km/h gear={motion.gear} v{runtime.simulator.state.state_version}")
    elif verb == "stop":
        await runtime.set_motion(0.0, "P")
    elif verb == "gear":
        if len(args) != 1 or args[0].upper() not in {"P", "R", "N", "D"}:
            print("cần: gear <P|R|N|D>")
        else:
            await runtime.set_motion(motion.speed_kph, args[0].upper())
    elif verb == "speed":
        try:
            speed = float(args[0])
        except (IndexError, ValueError):
            print("cần: speed <km/h> [gear]")
            return
        if speed < 0:
            print("tốc độ không âm được")
            return
        gear = args[1].upper() if len(args) > 1 else None
        if gear is not None and gear not in {"P", "R", "N", "D"}:
            print("gear phải là P/R/N/D")
            return
        await runtime.set_motion(speed, gear)
    else:
        print(_HELP)


async def _console_loop(runtime: SimulatorRuntime) -> None:
    """Đọc stdin trong thread riêng để không chẹn event loop.

    Cố ý **không** đòi stdin phải là TTY: chạy có kịch bản
    (`python -m src.vehicle_sim < kich-ban.txt`) cũng là cách dùng hợp lệ, và
    đòi TTY sẽ chặn luôn cả việc test cơ chế này. Dưới `docker compose up -d`
    thì stdin là /dev/null nên `readline` trả chuỗi rỗng ngay và vòng lặp thoát
    êm — không cần guard riêng.
    """
    if sys.stdin is None:
        logger.info("Không có stdin — bỏ qua console điều khiển chuyển động")
        return
    print(_HELP, flush=True)
    while True:
        try:
            line = await asyncio.to_thread(sys.stdin.readline)
        except (ValueError, OSError):  # stdin đóng giữa chừng
            return
        if not line:
            return
        try:
            await _apply_console_command(runtime, line.strip())
        except Exception:  # noqa: BLE001 — gõ sai không được giết xe ảo
            logger.exception("Lệnh console lỗi")


async def _drive_cycle_loop(runtime: SimulatorRuntime, speed_kph: float, phase_s: float, le_pha_s: float = 0.0) -> None:
    """Xe tự lặp 0 km/h ↔ `speed_kph`, mỗi pha `phase_s` giây — ADR-024 mục 7.

    Có mặt để BTC vào lúc nào cũng thấy một màn hình đang sống, kể cả khi không
    ai chạm thanh trượt. Gọi đúng `set_motion()` mà console gọi, nên nó không mở
    thêm bề mặt nào: không ACL, không topic, không route.

    Bắt đầu ở pha **đang chạy**. Xe khởi động ở 0 km/h số P, nên vào pha đứng yên
    trước là 30 giây đầu tiên không có gì thay đổi — đúng 30 giây mà một người
    vừa mở link sẽ nhìn.
    """
    logger.info(
        "Chu kỳ tự chạy %s: 0 ↔ %.1f km/h, mỗi pha %.0fs, lệch pha %.1fs",
        runtime.vehicle_id,
        speed_kph,
        phase_s,
        le_pha_s,
    )
    # Lệch pha giữa các xe: cả đội chạy đồng bộ thì MỌI tài xế bị khoá giao diện cùng
    # một lúc (`ui.policy` siết khi xe chạy), kể cả người đang trình bày. Lệch nhau thì
    # lúc nào cũng có xe đứng yên để thao tác và có xe đang chạy để nhìn.
    if le_pha_s:
        await asyncio.sleep(le_pha_s)
    while True:
        await runtime.set_motion(speed_kph, "D")
        await asyncio.sleep(phase_s)
        await runtime.set_motion(0.0, "P")
        await asyncio.sleep(phase_s)


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    )

    vehicle_ids = settings.vehicle_pool_ids()

    # MỘT KẾT NỐI MỖI XE — cố ý, dù backend thì ngược lại (K runtime chung một kết nối).
    #
    # Last Will gắn theo **kết nối**, không theo topic. Gộp K xe vào một client nghĩa là
    # cả đội chỉ có một LWT, nên khi tiến trình chết thì đúng một chiếc xe được báo
    # offline còn K-1 chiếc kia im lặng nằm đó với retained health `online=true` — backend
    # sẽ tin là chúng còn sống cho tới khi heartbeat quá hạn. Mất khả năng phát hiện
    # từng xe chết là mất đúng thứ cặp Birth+LWT sinh ra để có.
    #
    # Giá phải trả đã đo: ~13 KB mỗi xe (run `20260823T102102`), tức 100 xe tốn 1,3 MB.
    xe: list[tuple[SimulatorRuntime, AiomqttClient]] = []
    for vehicle_id in vehicle_ids:
        simulator = VehicleSimulator(vehicle_id)
        client = AiomqttClient(
            settings.mqtt_url,
            # client_id cố định + clean_session=False để giữ subscription qua
            # reconnect, không bỏ lỡ lệnh khi mất kết nối ngắn.
            client_id=f"vehicle-simulator-{vehicle_id}",
            username=settings.mqtt_simulator_username or None,
            password=settings.simulator_password() or None,
            clean_session=False,
            keepalive=30,
            will=will_for(vehicle_id),
        )
        runtime = SimulatorRuntime(
            simulator,
            client,
            heartbeat_interval_s=settings.mqtt_heartbeat_interval_s,
            sim_control_enabled=settings.sim_control_enabled,
        )
        await client.start()
        await runtime.start()
        xe.append((runtime, client))

    # Console gõ tay chỉ lái **ô số 0**. Nó là một kênh stdin duy nhất, nên hoặc phải
    # thêm cú pháp chọn xe (mở rộng một bề mặt gõ tay mà chỉ người trình bày dùng), hoặc
    # chọn một chiếc. Ô số 0 là chiếc mà tài liệu, healthcheck và màn kỹ sư đều trỏ tới.
    runtime = xe[0][0]

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows không có SIGTERM
            loop.add_signal_handler(sig, stop.set)

    console = asyncio.create_task(_console_loop(runtime), name="console")
    drive_cycles: list[asyncio.Task[None]] = []
    if settings.sim_drive_cycle:
        phase_s = settings.sim_drive_cycle_phase_s
        for i, (rt, _) in enumerate(xe):
            drive_cycles.append(
                asyncio.create_task(
                    _drive_cycle_loop(
                        rt,
                        settings.sim_drive_cycle_speed_kph,
                        phase_s,
                        le_pha_s=phase_s * i / max(len(xe), 1),
                    ),
                    name=f"drive-cycle-{rt.vehicle_id}",
                )
            )

    try:
        await stop.wait()
    finally:
        logger.info("Đang tắt %d xe ảo: %s", len(xe), ", ".join(vehicle_ids))
        for task in drive_cycles:
            # Khác `console`: task này chỉ ngủ chứ không chẹn ở `to_thread`, nên
            # await được sau cancel và tắt gọn ngay.
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        # `to_thread` đang chẹn ở readline nên task chỉ thật sự kết thúc khi có
        # dòng mới; cancel rồi đi tiếp, đừng await — nếu không Ctrl+C sẽ treo cho
        # tới khi người dùng gõ Enter.
        console.cancel()
        for rt, cl in xe:
            # `runtime.stop()` phát health `online=false, reason=shutdown` — phân biệt
            # được với LWT, nên phải chạy TRƯỚC khi đóng client của chính nó.
            await rt.stop()
            await cl.stop()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        # paho-mqtt cần selector loop, xem src/services/mqtt_client.py.
        #
        # Đặt policy TRƯỚC rồi gọi `asyncio.run(main())` trần, chứ KHÔNG truyền
        # `loop_factory=`: tham số đó chỉ tồn tại từ Python 3.12, còn repo chạy 3.11
        # (`requires-python = ">=3.11"`, cả hai workflow CI đều pin `3.11`). Trên 3.11
        # dòng cũ nổ `TypeError: run() got an unexpected keyword argument 'loop_factory'`
        # ngay khi khởi động, nên tầng test L3 — vốn spawn chính tiến trình này — không
        # bao giờ chạy được. `src/serve.py` đã né đúng bẫy này từ đầu; chỗ này bị bỏ sót.
        # `asyncio.run()` tạo loop qua policy, nên đặt policy là đủ.
        ensure_selector_event_loop()
        asyncio.run(main())
