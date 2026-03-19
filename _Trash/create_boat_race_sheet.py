import pandas as pd
import os

# Define the file path
file_path = "c:/Users/HP/OneDrive/ドキュメント/Play/boat_race_analysis.xlsx"

# Define the sheet names and columns based on the latest design
sheets = {
    # Consolidated raw logs
    "raw_results": [
        "race_date",   # A
        "venue",       # B
        "race_no",     # C
        "race_id",     # D
        "lane",        # E
        "player_id",   # F
        "player_name", # G
        "engine_no",   # H
        "rank",        # I
        "st",          # J
        "entry_count"  # K
    ],
    # Feature calculation sheet
    "features_daily": [
        "race_date",           # A
        "venue",               # B
        "race_no",             # C
        "race_id",             # D
        "lane",                # E
        "player_id",           # F
        "player_name",         # G
        "engine_no",           # H
        "recent_avg_rank",     # I
        "start_avg",           # J
        "engine_win_rate",     # K
        "lane_recent_win",     # L
        "field_win_rate",      # M
        "start_rank_relative", # N
        "feature_confidence_score" # O (Added for AI judgment)
    ],
    # Output sheet for GAS
    "ai_prompt_daily": ["prompt_text"]
}

# Create a Pandas Excel writer using openpyxl as the engine
writer = pd.ExcelWriter(file_path, engine='openpyxl')

# Create each sheet with headers
for sheet_name, columns in sheets.items():
    df = pd.DataFrame(columns=columns)
    df.to_excel(writer, sheet_name=sheet_name, index=False)
    
    # Logic for features_daily formulas
    if sheet_name == "features_daily":
        worksheet = writer.sheets[sheet_name]
        
        # Write formulas for 100 rows (starting from row 2)
        # Note: These use Google Sheets specific syntax (QUERY) which will work upon import
        for row in range(2, 102):
            # I: recent_avg_rank (Direct QUERY to raw_results)
            # Logic: Average rank for this player, before this date, limit 5
            # raw_results cols: A=date, F=player_id, I=rank
            query_recent = f'"select I where F = \'" & F{row} & "\' and A < date \'" & TEXT(A{row}, "yyyy-mm-dd") & "\' order by A desc limit 5"'
            f_recent = f'=IFERROR(AVERAGE(QUERY(raw_results!$A:$K, {query_recent})), "")'
            worksheet[f'I{row}'] = f_recent

            # J: start_avg (Same logic, target col J=st)
            query_st = f'"select J where F = \'" & F{row} & "\' and A < date \'" & TEXT(A{row}, "yyyy-mm-dd") & "\' order by A desc limit 5"'
            f_st = f'=IFERROR(AVERAGE(QUERY(raw_results!$A:$K, {query_st})), "")'
            worksheet[f'J{row}'] = f_st

            # K: engine_win_rate (COUNTIFS)
            # Logic: Same venue(B), Same motor(H), Date >= date-90. 1st place (rank=1) / Total
            # raw_results: B=venue, H=engine, A=date, I=rank
            matches_k = f'COUNTIFS(raw_results!$B:$B, $B{row}, raw_results!$H:$H, $H{row}, raw_results!$A:$A, ">="&$A{row}-90, raw_results!$A:$A, "<"&$A{row})'
            wins_k = f'COUNTIFS(raw_results!$B:$B, $B{row}, raw_results!$H:$H, $H{row}, raw_results!$A:$A, ">="&$A{row}-90, raw_results!$A:$A, "<"&$A{row}, raw_results!$I:$I, 1)'
            f_engine = f'=IF({matches_k} < 10, "", {wins_k} / {matches_k})'
            worksheet[f'K{row}'] = f_engine

            # L: lane_recent_win (COUNTIFS)
            # Logic: Same player(F), Same lane(E), Date >= date-90.
            matches_l = f'COUNTIFS(raw_results!$F:$F, $F{row}, raw_results!$E:$E, $E{row}, raw_results!$A:$A, ">="&$A{row}-90, raw_results!$A:$A, "<"&$A{row})'
            wins_l = f'COUNTIFS(raw_results!$F:$F, $F{row}, raw_results!$E:$E, $E{row}, raw_results!$A:$A, ">="&$A{row}-90, raw_results!$A:$A, "<"&$A{row}, raw_results!$I:$I, 1)'
            f_lane = f'=IF({matches_l} < 5, "", {wins_l} / {matches_l})'
            worksheet[f'L{row}'] = f_lane

            # M: field_win_rate (COUNTIFS)
            # Logic: Same player(F), Same venue(B), Date >= date-365. Rank <= 2
            matches_m = f'COUNTIFS(raw_results!$F:$F, $F{row}, raw_results!$B:$B, $B{row}, raw_results!$A:$A, ">="&$A{row}-365, raw_results!$A:$A, "<"&$A{row})'
            wins_m = f'COUNTIFS(raw_results!$F:$F, $F{row}, raw_results!$B:$B, $B{row}, raw_results!$A:$A, ">="&$A{row}-365, raw_results!$A:$A, "<"&$A{row}, raw_results!$I:$I, "<=2")'
            f_field = f'=IF({matches_m} < 10, "", {wins_m} / {matches_m})'
            worksheet[f'M{row}'] = f_field

            # N: start_rank_relative (RANK)
            # Logic: Rank of J (start_avg) within the same race_id (D)
            # Note: This is tricky in pure Excel without array formulas, but FILTER works in Sheets
            # =IF(J2="", "", RANK(J2, FILTER(J:J, D:D=D2), 1))
            f_rank = f'=IF($J{row}="", "", RANK($J{row}, FILTER($J:$J, $D:$D=$D{row}), 1))'
            worksheet[f'N{row}'] = f_rank

            # O: feature_confidence_score
            # Simple weighted formula: (WinRate90d*0.4 + FieldRate*0.2 + MotorRate*0.2 + LaneRate*0.1) - (ST_Avg*10)
            # Note: Features mapping changed slightly (no P:exhibition_time in this list, removed to match MVP).
            # Mapping based on current columns: K=Motor, L=Lane, M=Field. PlayerWinRate(G in old, now missing explicitly, using recent_avg_rank I inverted? Or just use what we have).
            # Let's align with the prompt's latest MVP which dropped player_win_rate column for raw calculation simplicity, or implied it comes from raw.
            # Actually, "recent_avg_rank" (I) is the player proxy.
            # Let's make a reasonable score:
            # Score = (Motor% * 100) + (Lane% * 100) + (Field% * 100) - (RankAvg * 10) - (ST * 100)
            # Handling blanks with N() or IFERROR is good practice.
            # Using N() for percentages.
            f_score = f'=IFERROR((N(K{row})*40) + (N(L{row})*20) + (N(M{row})*20) - (N(I{row})*5) - (N(J{row})*100) + 100, 0)'
            worksheet[f'O{row}'] = f_score

writer.close()
print(f"Successfully created {file_path}")
