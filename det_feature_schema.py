"""Det (LightGBM) で学習時と本番時に共通で使う特徴量一覧。"""


def live_feature_names():
    """本番の出走表・展示情報だけから必ず作れる特徴量を返す。"""
    names = ["R", "WindSpeed", "Wave", "WaterTemp"]
    for lane in range(1, 7):
        prefix = f"B{lane}_"
        names.extend([
            prefix + "WinRate", prefix + "Motor", prefix + "RankScore",
            prefix + "Tilt", prefix + "ExTime", prefix + "Course_Win",
            prefix + "Course_2in", prefix + "Course_3in", prefix + "Weight",
        ])
    names.extend([
        "Diff_WinRate_1_2", "Avg_WinRate", "B1_WinRate_Over_Avg",
        "VenueID", "Month", "ExTime_Min", "ExTime_Max", "ExTime_Spread",
        "B1_ExTime_vs_Min", "B1_ExTime_vs_Avg", "Max_WinRate",
        "WinRate_Spread", "B1_Is_Top_WinRate", "Max_Outer_WinRate",
        "Diff_B1_vs_MaxOuter", "Avg_RankScore", "B1_RankScore_Over_Avg",
        "WindDirCode", "IsHeadwind", "Headwind_x_Speed",
    ])
    return tuple(names)


LIVE_FEATURE_NAMES = live_feature_names()


def select_live_features(columns):
    """学習データに実在する本番互換特徴量だけを、固定順で選ぶ。"""
    available = set(columns)
    return [name for name in LIVE_FEATURE_NAMES if name in available]
