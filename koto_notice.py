"""ボートレースAIのお知らせを、KOTO（ことちゃん）経由で本人へ届ける（2026-10-23、LINE卒業の準備）。

KOTO の入口 /api/owner-notice へ送ると、KOTO が LINE とスマホのアプリ（SmartVoice）の両方へ届ける。
- 送り先と合言葉は credentials.env の KOTO_NOTICE_URL / KOTO_NOTICE_KEY（無ければ KOTO へは送らない）。
- KOTO へ届けられなかったときは False を返す。呼び出し側は今までどおり LINE へ直接送る（予備）。
- 合言葉は通信の見出し（Authorization）で渡し、画面やログには出さない。
"""

import hashlib
import os
from datetime import datetime

TIMEOUT_SECONDS = 15
MESSAGE_MAX = 10_000


def notice_id_for(topic: str, message: str, now: datetime | None = None) -> str:
    """同じお知らせの再送を KOTO が見分けるための番号（話題・日付・本文から決まる）。"""
    day = (now or datetime.now()).strftime("%Y%m%d")
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()[:12]
    return f"{topic}-{day}-{digest}"


def send_via_koto(topic: str, message: str, notice_id: str | None = None) -> bool:
    """KOTO へお知らせを送る。届いたら True。設定が無い・失敗したら False（例外は出さない）。"""
    url = os.environ.get("KOTO_NOTICE_URL", "").strip()
    key = os.environ.get("KOTO_NOTICE_KEY", "").strip()
    if not url or not key:
        return False
    if not url.startswith("https://"):
        print("  [WARN] KOTO_NOTICE_URL が https ではないため、KOTO 経由の送信をしませんでした。")
        return False
    if not message or not message.strip():
        return False
    text = message if len(message) <= MESSAGE_MAX else message[: MESSAGE_MAX - 20] + "\n…（省略）"
    payload = {"topic": topic, "message": text, "id": notice_id or notice_id_for(topic, text)}
    try:
        import requests
    except Exception as error:
        print(f"  [WARN] KOTO 経由の送信ができません: {type(error).__name__}")
        return False

    # 返事が遅れたとき、KOTO はもう LINE へ送り終えていることがある。すぐ LINE へ直接送ると2通届くので、
    # 同じ番号でもう1回だけ KOTO に送る（KOTO は同じ番号を「受け取り済み」として 200 を返す）。code-check 10/23
    for attempt in (1, 2):
        try:
            response = requests.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {key}"},
                timeout=TIMEOUT_SECONDS,
            )
        except requests.exceptions.Timeout:
            if attempt == 1:
                print("  [WARN] KOTO の返事が遅いため、同じ番号でもう1回だけ送ります。")
                continue
            print("  [WARN] KOTO 経由の送信に失敗しました: Timeout")
            return False
        except Exception as error:
            print(f"  [WARN] KOTO 経由の送信に失敗しました: {type(error).__name__}")
            return False
        if response.status_code == 200:
            print("  [SUCCESS] KOTO 経由でお知らせを送りました（LINE とアプリへ）。")
            return True
        print(f"  [WARN] KOTO 経由の送信に失敗しました: HTTP {response.status_code}")
        return False
    return False
