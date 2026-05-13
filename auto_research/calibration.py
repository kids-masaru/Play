"""
calibration.py - 確率較正モジュール

LightGBM多クラスモデルの生確率を Isotonic Regression で較正する。
低確率レンジでの過大評価（モデルが「3%」と言ってるが実際は0.5%等）を補正し、
EV=prob×odds 計算を信頼可能にする。

使い方:
    cal = MultiClassCalibrator(num_classes=6)
    cal.fit(raw_probs_calib, y_true_calib)
    calibrated = cal.transform(raw_probs_test)
"""
import numpy as np
import pickle
from sklearn.isotonic import IsotonicRegression


class MultiClassCalibrator:
    """各クラスに1つずつ IsotonicRegression を割り当てる one-vs-rest 較正器。

    多クラス確率を per-class で較正し、最後に行ごとに正規化して
    Σp = 1 を維持する。
    """

    def __init__(self, num_classes: int = 6):
        self.num_classes = num_classes
        self.calibrators: list[IsotonicRegression] = []

    def fit(self, raw_probs: np.ndarray, y_true: np.ndarray) -> "MultiClassCalibrator":
        """
        Args:
            raw_probs: shape (N, num_classes) のモデル生確率
            y_true: shape (N,) の正解クラス (0-indexed)
        """
        if raw_probs.shape[1] != self.num_classes:
            raise ValueError(f"raw_probs.shape[1] {raw_probs.shape[1]} != num_classes {self.num_classes}")
        self.calibrators = []
        for k in range(self.num_classes):
            ir = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            ir.fit(raw_probs[:, k], (y_true == k).astype(np.float64))
            self.calibrators.append(ir)
        return self

    def transform(self, raw_probs: np.ndarray) -> np.ndarray:
        """較正済み確率を返す（行ごとに sum=1 に正規化）"""
        if not self.calibrators:
            raise RuntimeError("fit() を先に呼んでください")
        calibrated = np.zeros_like(raw_probs, dtype=np.float64)
        for k in range(self.num_classes):
            calibrated[:, k] = self.calibrators[k].transform(raw_probs[:, k])
        # 0除算回避
        row_sums = calibrated.sum(axis=1, keepdims=True)
        row_sums = np.where(row_sums < 1e-10, 1.0, row_sums)
        return calibrated / row_sums

    def save(self, path: str) -> None:
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path: str) -> "MultiClassCalibrator":
        with open(path, "rb") as f:
            return pickle.load(f)


def fit_three_calibrators(probs_1st, probs_2nd, probs_3rd, y_1st, y_2nd, y_3rd, num_classes=6):
    """1着/2着/3着モデル用に3つの較正器を一括 fit する便利関数"""
    cals = {}
    for name, p, y in [("1st", probs_1st, y_1st), ("2nd", probs_2nd, y_2nd), ("3rd", probs_3rd, y_3rd)]:
        cals[name] = MultiClassCalibrator(num_classes=num_classes).fit(p, y)
    return cals


if __name__ == "__main__":
    # 簡易サニティテスト
    rng = np.random.default_rng(42)
    n = 1000
    # 真の分布: クラスk の真の確率は k / sum(0..5)
    y = rng.choice(6, size=n, p=[0.5, 0.25, 0.1, 0.07, 0.05, 0.03])
    # 生確率: 真の分布をノイズ付きで観測
    raw = np.zeros((n, 6))
    for i in range(n):
        true_dist = np.array([0.5, 0.25, 0.1, 0.07, 0.05, 0.03])
        # クラス y[i] にバイアスを乗せて出力
        raw[i] = true_dist + rng.normal(0, 0.05, 6)
        raw[i, y[i]] += 0.2
        raw[i] = np.clip(raw[i], 1e-4, 1)
        raw[i] /= raw[i].sum()

    cal = MultiClassCalibrator(6).fit(raw, y)
    calibrated = cal.transform(raw)
    print("生確率 平均:", raw.mean(axis=0).round(4))
    print("較正後 平均:", calibrated.mean(axis=0).round(4))
    print("実際の頻度:", np.bincount(y, minlength=6) / n)
    print("テスト完了")
