"""sync_playwright がメインスレッドで起動できるか最小再現テスト。"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print("Step1: collect_race_data import")
from collect_race_data import VENUE_MAP
print(f"  VENUE_MAP keys: {len(VENUE_MAP)}")

print("Step2: playwright import")
from playwright.sync_api import sync_playwright

print("Step3: sync_playwright().start() main thread")
pw = sync_playwright().start()
print("  OK: main-thread start succeeded")

print("Step4: chromium launch")
br = pw.chromium.launch(headless=True)
print("  OK: browser launched")

br.close()
pw.stop()
print("Done")
