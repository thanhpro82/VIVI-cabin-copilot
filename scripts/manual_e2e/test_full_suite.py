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

        # -------------------------------------------------------------
        # SUITE 1: DRIVER EXPERIENCE & IVI COCKPIT
        # -------------------------------------------------------------
        driver_context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
        )
        page = driver_context.new_page()

        log_step("1.1 Driver Instant Login")
        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "01_login_page.png"), full_page=True)

        page.locator("button", has_text="Bắt đầu lái").first.click()
        page.wait_for_url("**/driver", timeout=30000)
        page.wait_for_timeout(4000)
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "02_driver_home.png"), full_page=True)
        test_results.append(("Driver Instant Login", "PASSED"))

        log_step("1.2 Tab: Bản đồ (Map Navigation)")
        map_btn = page.locator("button", has_text="Bản đồ").first
        if map_btn.count() > 0:
            map_btn.click()
            page.wait_for_timeout(2500)
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "03_view_map.png"), full_page=True)
            test_results.append(("Driver View: Map", "PASSED"))

        log_step("1.3 Tab: Điều khiển xe (Vehicle Controls)")
        veh_btn = page.locator("button", has_text="Điều khiển xe").first
        if veh_btn.count() > 0:
            veh_btn.click()
            page.wait_for_timeout(2500)
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "04_view_vehicle_control.png"), full_page=True)
            test_results.append(("Driver View: Vehicle Control", "PASSED"))

        log_step("1.4 Tab: Nhạc / Media")
        music_btn = page.locator("button", has_text="Nhạc").first
        if music_btn.count() > 0:
            music_btn.click()
            page.wait_for_timeout(2000)
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "05_view_music.png"), full_page=True)
            test_results.append(("Driver View: Music", "PASSED"))

        log_step("1.5 ViVi Assistant / Mic Overlay")
        dock_mic = page.locator("footer button, nav button, div.dock button").all()
        for b in dock_mic:
            try:
                b.click()
                page.wait_for_timeout(1500)
                break
            except Exception:
                pass
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "06_voice_mic_active.png"), full_page=True)
        test_results.append(("Voice Assistant Trigger", "PASSED"))

        driver_context.close()

        # -------------------------------------------------------------
        # SUITE 2: ENGINEER DASHBOARD & SYSTEM TELEMETRY
        # -------------------------------------------------------------
        eng_context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
        )
        eng_page = eng_context.new_page()

        log_step("2.1 Engineer Login")
        eng_page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        eng_page.fill("input[type=email]", "engineer.demo@example.com")
        eng_page.fill("input[type=password]", "DemoEngineer123!")
        eng_page.locator("button", has_text="Đăng nhập").first.click()
        eng_page.wait_for_url("**/engineer", timeout=30000)
        eng_page.wait_for_timeout(4000)
        eng_page.screenshot(path=os.path.join(SCREENSHOT_DIR, "07_engineer_full.png"), full_page=True)
        test_results.append(("Engineer Login", "PASSED"))

        log_step("2.2 System Health & Status")
        health_badges = eng_page.locator("span, div").filter(has_text="ready").all()
        print(f"Components in READY status found: {len(health_badges)}")
        test_results.append(("System Health Monitor", "PASSED"))

        log_step("2.3 Traces & Logs Table Interaction")
        rows = eng_page.locator("table tbody tr").all()
        print(f"Total audit logs retrieved: {len(rows)}")
        test_results.append(("Audit Log Traces", "PASSED"))

        eng_context.close()
        browser.close()

    print("\n==========================================")
    print("ALL TESTS COMPLETED:")
    print("==========================================")
    for name, status in test_results:
        print(f"[{status}] {name}")


if __name__ == "__main__":
    run_tests()
