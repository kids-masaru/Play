"""保存済みの新旧Detモデルを再学習せずに同じ時系列テストで比較する。"""
from retrain_model import (
    MODEL_FILE, MODEL_BACKUP, MODEL_FILE_2ND, MODEL_BACKUP_2ND,
    MODEL_FILE_3RD, MODEL_BACKUP_3RD, evaluate_saved_model,
)


def main():
    pairs = [
        ("1着予測", "Target_1st", MODEL_FILE, MODEL_BACKUP),
        ("2着予測", "Target_2nd", MODEL_FILE_2ND, MODEL_BACKUP_2ND),
        ("3着予測", "Target_3rd", MODEL_FILE_3RD, MODEL_BACKUP_3RD),
    ]
    print("=== Det 新旧モデル比較（再学習なし）===")
    for label, target, current, backup in pairs:
        new_acc = evaluate_saved_model(current, target, f"{label} 新モデル")
        old_acc = evaluate_saved_model(backup, target, f"{label} 旧モデル")
        print(f"[{label}] 新 {new_acc * 100:.2f}% / 旧 {old_acc * 100:.2f}%")


if __name__ == "__main__":
    main()
