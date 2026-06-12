"""scrape_past_odds_parallel.py の冒頭をそのまま真似た最小再現。"""
import os
import sys
import io
import csv
import time
import threading
import queue
from datetime import datetime, date, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from collect_race_data import get_venues_for_date, VENUE_MAP

print("Imports done")

from playwright.sync_api import sync_playwright
print("playwright imported")

pw = sync_playwright().start()
print("started OK")
br = pw.chromium.launch(headless=True)
print("browser launched OK")
br.close()
pw.stop()
print("Done")
