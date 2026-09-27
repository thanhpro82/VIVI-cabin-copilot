import io
import os
import sys

from playwright.sync_api import sync_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SCREENSHOT_DIR = os.path.join(os.getcwd(), "test_results", "slm_web_tests")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

BASE_URL = os.getenv("E2E_BASE_URL", "https://c4-app-192.io.vn")


def log_test(case_id: str, name: str) -> None:
    print("\n==========================================")
    print(f"🤖 [TEST SLM WEB {case_id}] {name}")
    print("==========================================")


def run_slm_web_tests():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        print("1. Đăng nhập Driver...")
        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.locator("button", has_text="Bắt đầu lái").first.click()
        page.wait_for_url("**/driver", timeout=30000)
        page.wait_for_timeout(4000)
        print("-> Đã vào /driver thành công!")

        def send_turn_on_web(text):
            print(f'Gửi câu lệnh: "{text}"')
            res = page.evaluate(
                """(msg) => {
                const authStr = localStorage.getItem('vivi.session');
                const auth = JSON.parse(authStr);
                const token = auth.accessToken;
                const driverSessionStr = localStorage.getItem('vivi.driver_session');
                const driverSession = JSON.parse(driverSessionStr);
                const sessionId = driverSession.sessionId;

                return fetch('/api/v1/turns/text', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': 'Bearer ' + token,
                        'X-Schema-Version': '1.0',
                        'Idempotency-Key': 'web-test-' + Date.now()
                    },
                    body: JSON.stringify({
                        session_id: sessionId,
                        text: msg
                    })
                }).then(r => r.json());
            }""",
                text,
            )
            return res

        # CASE 1: LỆNH ĐIỀU KHIỂN XE
        log_test("TC-SLM-01", "Lệnh điều khiển xe: Bật điều hòa 21 độ")
        res1 = send_turn_on_web("Bật điều hòa 21 độ")
        print("Kết quả backend:", res1.get("data", {}).get("response", {}).get("display_text"))
        veh_btn = page.locator("button", has_text="Điều khiển xe").first
        if veh_btn.count() > 0:
            veh_btn.click()
        page.wait_for_timeout(3000)
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "01_slm_control_turn.png"), full_page=True)

        # CASE 2: TRA CỨU SỔ TAY XE (RAG)
        log_test("TC-SLM-02", "Tra cứu sổ tay: Xe có tự giữ làn đường không?")
        res2 = send_turn_on_web("Xe có tự giữ làn đường không?")
        ans2 = res2.get("data", {}).get("response", {})
        print("Câu trả lời RAG:", (ans2.get("display_text") or "")[:150] + "...")
        print("Số trích dẫn:", len(ans2.get("citations", [])))
        page.wait_for_timeout(3000)
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "02_slm_rag_turn.png"), full_page=True)

        # CASE 3: TRÒ CHUYỆN / CHITCHAT
        log_test("TC-SLM-03", "Trò chuyện / Chitchat: Xin chào ViVi")
        res3 = send_turn_on_web("Xin chào ViVi, bạn có thể làm được gì?")
        print("Phản hồi Chitchat:", res3.get("data", {}).get("response", {}).get("display_text"))
        page.wait_for_timeout(3000)
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "03_slm_chitchat_turn.png"), full_page=True)

        # CASE 4: THAO TÁC AN TOÀN S2
        log_test("TC-SLM-04", "Thao tác an toàn S2 (HITL Approval): Mở cốp xe")
        res4 = send_turn_on_web("Mở cốp xe")
        pending = res4.get("data", {}).get("pending_approval")
        print("Pending Approval ID:", pending.get("approval_id") if pending else "None")
        page.wait_for_timeout(3000)
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "04_slm_hitl_approval_modal.png"), full_page=True)

        # CASE 5: ENGINEER DASHBOARD
        log_test("TC-SLM-05", "Kiểm tra thống kê các lượt SLM trên Engineer Dashboard")
        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.fill("input[type=email]", "engineer.demo@example.com")
        page.fill("input[type=password]", "DemoEngineer123!")
        page.locator("button", has_text="Đăng nhập").first.click()
        page.wait_for_url("**/engineer", timeout=30000)
        page.wait_for_timeout(4000)
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "05_slm_engineer_metrics.png"), full_page=True)
        print("-> Đã kiểm tra Engineer Dashboard sau khi chạy SLM turns!")

        browser.close()
        print("\n🎉 Hoàn thành toàn bộ test case SLM trực tiếp trên Web!")


if __name__ == "__main__":
    run_slm_web_tests()
