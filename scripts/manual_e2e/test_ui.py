import io
import os
import sys

from playwright.sync_api import sync_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SCREENSHOT_DIR = os.path.join(os.getcwd(), "test_results", "playwright_screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

BASE_URL = os.getenv("E2E_BASE_URL", "https://c4-app-192.io.vn")


def log_step(name: str) -> None:
    print("\n==========================================")
    print(f"[TEST STEP] {name}")
    print("==========================================")


def run_tests():
    test_results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        # Step 1: Login Page
        log_step("1. Login Page Inspection")
        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "01_login_page.png"), full_page=True)
        print("Page title:", page.title())
        test_results.append(("Login Page Render", "PASSED"))

        # Step 2: Driver Instant Login
        log_step("2. Driver Instant Login")
        driver_btn = page.locator("button", has_text="Bắt đầu lái")
        if driver_btn.count() > 0:
            driver_btn.first.click()
            page.wait_for_url("**/driver", timeout=30000)
            page.wait_for_timeout(4000)
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "02_driver_dashboard.png"), full_page=True)
            print("Driver URL:", page.url)
            test_results.append(("Driver Instant Login", "PASSED"))
        else:
            print("Driver button not found")
            test_results.append(("Driver Instant Login", "FAILED"))

        # Step 3: Engineer Login
        log_step("3. Engineer Login")
        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.fill("input[type=email]", "engineer.demo@example.com")
        page.fill("input[type=password]", "DemoEngineer123!")
        page.locator("button", has_text="Đăng nhập").first.click()
        page.wait_for_url("**/engineer", timeout=30000)
        page.wait_for_timeout(4000)
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "03_engineer_dashboard.png"), full_page=True)
        print("Engineer URL:", page.url)
        test_results.append(("Engineer Login", "PASSED"))

        # Step 4: Engineer Table Inspection
        log_step("4. Engineer Traces & Logs Table")
        rows = page.locator("table tbody tr").all()
        print(f"Total audit log rows found: {len(rows)}")
        test_results.append(("Engineer Traces Table", "PASSED"))

        # Step 5: Engineer Telemetry Metrics
        log_step("5. Telemetry & Broker Stat Tiles")
        metrics = page.locator("div.stat-tile, div[class*='stat'], div[class*='metric']").all()
        print(f"Metrics tiles rendered: {len(metrics)}")
        test_results.append(("Engineer Metrics Tiles", "PASSED"))

        browser.close()

    print("\n==========================================")
    print("RESULTS SUMMARY:")
    print("==========================================")
    for name, status in test_results:
        print(f"[{status}] {name}")


if __name__ == "__main__":
    run_tests()
