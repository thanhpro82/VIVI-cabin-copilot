import io
import os
import sys

from playwright.sync_api import sync_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SCREENSHOT_DIR = os.path.join(os.getcwd(), "test_results", "playwright_screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

BASE_URL = os.getenv("E2E_BASE_URL", "https://c4-app-192.io.vn")


def log_step(step_name: str) -> None:
    print("\n=========================================")
    print(f"[TEST STEP] {step_name}")
    print("=========================================")


def run_tests():
    test_results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        # 1. TEST SUITE: LOGIN PAGE
        log_step("1.1 Truy cập trang Login & Kiểm tra UI")
        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "01_login_page.png"), full_page=True)

        title = page.title()
        print(f"Page Title: {title}")
        assert "VIVI" in title, f"unexpected title: {title}"

        driver_btn = page.locator("button:has-text('Bắt đầu lái')")
        eng_login_btn = page.locator("button:has-text('Đăng nhập')")
        assert driver_btn.is_visible(), "Driver login button not visible"
        assert eng_login_btn.is_visible(), "Engineer login button not visible"
        test_results.append(("Login Page Render", "PASSED"))

        log_step("1.2 Thử nghiệm Đăng nhập Sai thông tin (Form Validation)")
        page.fill("input[type='email']", "wrong@vivi.dev")
        page.fill("input[type='password']", "WrongPassword123!")
        eng_login_btn.click()
        page.wait_for_timeout(2000)
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "02_login_invalid_credentials.png"), full_page=True)
        print(f"Current URL after invalid login: {page.url}")
        assert "/login" in page.url, "Should remain on /login after failed auth"
        test_results.append(("Invalid Login Validation", "PASSED"))

        # 2. TEST SUITE: DRIVER INSTANT LOGIN & IVI DASHBOARD
        log_step("2.1 Đăng nhập vai trò Tài xế (Driver Instant Login)")
        driver_btn.click()
        page.wait_for_url("**/driver", timeout=20000)
        page.wait_for_timeout(4000)
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "03_driver_dashboard_home.png"), full_page=True)
        print(f"Logged in as Driver! Current URL: {page.url}")
        assert "/driver" in page.url, "Failed to navigate to /driver"
        test_results.append(("Driver Instant Login & Landing", "PASSED"))

        log_step("2.2 Khám phá các nút chức năng trên Cockpit")
        page.wait_for_timeout(2000)
        buttons = page.locator("button").all()
        print(f"Total interactive buttons found on Driver Cockpit: {len(buttons)}")
        btn_texts = []
        for btn in buttons:
            try:
                txt = btn.inner_text().strip()
                if txt:
                    btn_texts.append(txt)
            except Exception:
                pass
        print("Driver Cockpit Buttons Sample:", btn_texts[:15])

        log_step("2.3 Thử chuyển đổi các view trên Dock")
        for view_name in ["Bản đồ", "Điều khiển xe", "Giải trí", "Cài đặt", "Xe", "Media", "Nhạc"]:
            btn = page.locator(f"button:has-text('{view_name}')").first
            if btn.count() > 0 and btn.is_visible():
                print(f"-> Click tab: {view_name}")
                btn.click()
                page.wait_for_timeout(1500)
                safe_name = view_name.replace(" ", "_").lower()
                page.screenshot(path=os.path.join(SCREENSHOT_DIR, f"04_driver_view_{safe_name}.png"))

        test_results.append(("Driver Cockpit & Dock Views", "PASSED"))

        # 3. TEST SUITE: ENGINEER DASHBOARD
        log_step("3.1 Đăng nhập Kỹ sư hệ thống (Engineer)")
        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.fill("input[type='email']", "engineer.demo@example.com")
        page.fill("input[type='password']", "DemoEngineer123!")
        page.locator("button:has-text('Đăng nhập')").click()
        page.wait_for_url("**/engineer", timeout=20000)
        page.wait_for_timeout(4000)
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "05_engineer_dashboard.png"), full_page=True)
        print(f"Logged in as Engineer! Current URL: {page.url}")
        assert "/engineer" in page.url, "Failed to navigate to /engineer"
        test_results.append(("Engineer Login & Dashboard", "PASSED"))

        log_step("3.2 Kiểm tra Responsive (Tablet & Mobile)")
        page.set_viewport_size({"width": 820, "height": 1180})
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "06_engineer_tablet.png"), full_page=True)

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "07_engineer_mobile.png"), full_page=True)
        test_results.append(("Engineer Responsive (Tablet, Mobile)", "PASSED"))

        browser.close()

    print("\n========================================")
    print("TỔNG HỢP KẾT QUẢ TEST PLAYWRIGHT:")
    print("========================================")
    for test_name, status in test_results:
        print(f"✅ {test_name}: {status}")


if __name__ == "__main__":
    run_tests()
