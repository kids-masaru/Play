import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timezone, timedelta

f = open('boatraceauto-b2bfa32e72bc.json', 'r')
d = json.load(f)
f.close()
creds = service_account.Credentials.from_service_account_info(d, scopes=['https://www.googleapis.com/auth/spreadsheets'])
svc = build('sheets', 'v4', credentials=creds)
sid = '1ixdf0Ep4DWSYPPED0xwCqwuG0U-aRSyl_5JI801Jk4Q'

# features_daily
fd = svc.spreadsheets().values().get(spreadsheetId=sid, range='features_daily').execute().get('values', [])
print(f"features_daily: {len(fd)} rows")
if len(fd) > 1:
    print(f"Sample row len: {len(fd[1])}")
    print(f"Sample row: {fd[1]}")

# AI_Analysis
aa = svc.spreadsheets().values().get(spreadsheetId=sid, range='AI_Analysis').execute().get('values', [])
print(f"\nAI_Analysis: {len(aa)} rows")
if aa:
    print(f"Header: {aa[0]}")
if len(aa) > 1:
    print(f"First data: {aa[1][:4]}")

# Phase 1 simulation
JST = timezone(timedelta(hours=9))
today = datetime.now(JST).strftime("%Y-%m-%d")
print(f"\ntoday: {today}")
short = 0
old = 0
ok = 0
for row in fd[1:]:
    if len(row) < 12:
        short += 1
        continue
    if row[0] < today:
        old += 1
        continue
    ok += 1
print(f"len<12 (skip): {short}")
print(f"date<today (skip): {old}")
print(f"OK (pass): {ok}")
