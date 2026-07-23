"""Notification text translations. Same placeholder-English-everywhere
convention as the frontend locale files (en.json/ja.json/ko.json/zh.json/
hi.json): Claude only wires up the keys and structure here -- the actual
ja/ko/zh/hi translation content gets filled in separately, by a human
translator, exactly like the frontend does. Uses the same {{param}}
interpolation syntax as the frontend's i18next setup, for consistency
across the whole system rather than introducing a second convention.
"""
import re

_PARAM_PATTERN = re.compile(r"\{\{(\w+)\}\}")

TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "health.moodWaterCheckin.title": "Quick check-in",
        "health.moodWaterCheckin.body": "How are you feeling, and have you had some water?",
        "health.sleepCheckin.title": "Sleep check-in",
        "health.sleepCheckin.body": "How did you sleep last night?",

        "attendance.presenceCheck.title": "Are you there?",
        "attendance.presenceCheck.body": "Quick check-in — tap to confirm you're okay.",

        "attendance.deskLocationRequest.title": "Desk location change requested",
        "attendance.deskLocationRequest.body": "{{name}} requested a desk location update.",

        "attendance.deskLocationDecisionApproved.title": "Desk location update approved",
        "attendance.deskLocationDecisionApproved.body": "Your desk location update was approved and is now active.",
        "attendance.deskLocationDecisionRejected.title": "Desk location update not approved",
        "attendance.deskLocationDecisionRejected.body": "Your desk location update request was not approved.",

        "attendance.shiftStartReminder.title": "Shift starting soon",
        "attendance.shiftStartReminder.body": "Your shift starts at {{time}} — check in when you're ready.",
        "attendance.shiftEndReminder.title": "Shift ending soon",
        "attendance.shiftEndReminder.body": "Your shift ends in about 15 minutes — don't forget to check out.",

        "alert.escalated.title": "Alert escalated",
        "alert.escalated.body": "An unacknowledged {{alertType}} alert needs attention.",
    },
    "ja": {
        "health.moodWaterCheckin.title": "クイックチェックイン",
        "health.moodWaterCheckin.body": "体調はいかがですか？水分は取れていますか？",
        "health.sleepCheckin.title": "睡眠チェックイン",
        "health.sleepCheckin.body": "昨夜はよく眠れましたか？",

        "attendance.presenceCheck.title": "いますか？",
        "attendance.presenceCheck.body": "クイックチェックイン — タップして安全を確認してください。",

        "attendance.deskLocationRequest.title": "デスク場所の変更リクエスト",
        "attendance.deskLocationRequest.body": "{{name}} がデスク場所の更新をリクエストしました。",

        "attendance.deskLocationDecisionApproved.title": "デスク場所の更新が承認されました",
        "attendance.deskLocationDecisionApproved.body": "デスク場所の更新が承認され、現在有効です。",
        "attendance.deskLocationDecisionRejected.title": "デスク場所の更新が却下されました",
        "attendance.deskLocationDecisionRejected.body": "デスク場所の更新リクエストは承認されませんでした。",

        "attendance.shiftStartReminder.title": "シフト開始まもなく",
        "attendance.shiftStartReminder.body": "シフトは {{time}} に始まります — 準備ができたらチェックインしてください。",
        "attendance.shiftEndReminder.title": "シフト終了まもなく",
        "attendance.shiftEndReminder.body": "シフトが約15分後に終了します — チェックアウトを忘れずに。",

        "alert.escalated.title": "アラートがエスカレートされました",
        "alert.escalated.body": "未確認の {{alertType}} アラートへの対応が必要です。",
    },
    "ko": {
        "health.moodWaterCheckin.title": "빠른 체크인",
        "health.moodWaterCheckin.body": "기분은 어떠세요? 물은 마셨나요?",
        "health.sleepCheckin.title": "수면 체크인",
        "health.sleepCheckin.body": "지난밤 잘 주무셨나요?",

        "attendance.presenceCheck.title": "거기 있나요?",
        "attendance.presenceCheck.body": "빠른 체크인 — 탭하여 괜찮음을 확인해 주세요.",

        "attendance.deskLocationRequest.title": "자리 위치 변경 요청됨",
        "attendance.deskLocationRequest.body": "{{name}} 님이 자리 위치 업데이트를 요청했습니다.",

        "attendance.deskLocationDecisionApproved.title": "자리 위치 업데이트 승인됨",
        "attendance.deskLocationDecisionApproved.body": "자리 위치 업데이트가 승인되어 현재 적용 중입니다.",
        "attendance.deskLocationDecisionRejected.title": "자리 위치 업데이트 미승인",
        "attendance.deskLocationDecisionRejected.body": "자리 위치 업데이트 요청이 승인되지 않았습니다.",

        "attendance.shiftStartReminder.title": "교대 시작 임박",
        "attendance.shiftStartReminder.body": "교대가 {{time}} 에 시작됩니다 — 준비되면 체크인하세요.",
        "attendance.shiftEndReminder.title": "교대 종료 임박",
        "attendance.shiftEndReminder.body": "교대가 약 15분 후 종료됩니다 — 체크아웃을 잊지 마세요.",

        "alert.escalated.title": "알림 에스컬레이션됨",
        "alert.escalated.body": "확인되지 않은 {{alertType}} 알림에 주의가 필요합니다.",
    },
    "zh": {
        "health.moodWaterCheckin.title": "快速签到",
        "health.moodWaterCheckin.body": "您感觉怎么样？喝水了吗？",
        "health.sleepCheckin.title": "睡眠签到",
        "health.sleepCheckin.body": "昨晚睡得好吗？",

        "attendance.presenceCheck.title": "你在吗？",
        "attendance.presenceCheck.body": "快速签到 — 点击确认您一切安好。",

        "attendance.deskLocationRequest.title": "已请求更改座位位置",
        "attendance.deskLocationRequest.body": "{{name}} 请求更新座位位置。",

        "attendance.deskLocationDecisionApproved.title": "座位位置更新已批准",
        "attendance.deskLocationDecisionApproved.body": "您的座位位置更新已获批准并已生效。",
        "attendance.deskLocationDecisionRejected.title": "座位位置更新未获批准",
        "attendance.deskLocationDecisionRejected.body": "您的座位位置更新请求未获批准。",

        "attendance.shiftStartReminder.title": "班次即将开始",
        "attendance.shiftStartReminder.body": "您的班次将于 {{time}} 开始 — 准备好后请签到。",
        "attendance.shiftEndReminder.title": "班次即将结束",
        "attendance.shiftEndReminder.body": "您的班次约15分钟后结束 — 别忘了签退。",

        "alert.escalated.title": "警报已升级",
        "alert.escalated.body": "一条未确认的 {{alertType}} 警报需要处理。",
    },
    "hi": {
        "health.moodWaterCheckin.title": "त्वरित चेक-इन",
        "health.moodWaterCheckin.body": "आप कैसा महसूस कर रहे हैं, और क्या आपने पानी पिया?",
        "health.sleepCheckin.title": "नींद चेक-इन",
        "health.sleepCheckin.body": "कल रात आपकी नींद कैसी रही?",

        "attendance.presenceCheck.title": "क्या आप वहाँ हैं?",
        "attendance.presenceCheck.body": "त्वरित चेक-इन — ठीक होने की पुष्टि के लिए टैप करें।",

        "attendance.deskLocationRequest.title": "डेस्क स्थान परिवर्तन अनुरोध",
        "attendance.deskLocationRequest.body": "{{name}} ने डेस्क स्थान अपडेट का अनुरोध किया।",

        "attendance.deskLocationDecisionApproved.title": "डेस्क स्थान अपडेट स्वीकृत",
        "attendance.deskLocationDecisionApproved.body": "आपका डेस्क स्थान अपडेट स्वीकृत हो गया है और अब सक्रिय है।",
        "attendance.deskLocationDecisionRejected.title": "डेस्क स्थान अपडेट अस्वीकृत",
        "attendance.deskLocationDecisionRejected.body": "आपका डेस्क स्थान अपडेट अनुरोध स्वीकृत नहीं किया गया।",

        "attendance.shiftStartReminder.title": "शिफ्ट जल्द शुरू होगी",
        "attendance.shiftStartReminder.body": "आपकी शिफ्ट {{time}} पर शुरू होती है — तैयार होने पर चेक इन करें।",
        "attendance.shiftEndReminder.title": "शिफ्ट जल्द समाप्त होगी",
        "attendance.shiftEndReminder.body": "आपकी शिफ्ट लगभग 15 मिनट में समाप्त होती है — चेक आउट करना न भूलें।",

        "alert.escalated.title": "अलर्ट एस्केलेट किया गया",
        "alert.escalated.body": "एक अपुष्ट {{alertType}} अलर्ट पर ध्यान देने की आवश्यकता है।",
    },
}

DEFAULT_LANGUAGE = "en"


def translate(language: str | None, key: str, params: dict | None = None) -> str:
    """Resolves a notification text key for the given language, falling
    back to English if the language is unsupported OR the specific key
    hasn't been translated into it yet (since ja/ko/zh/hi start out empty
    and get filled in over time, same as the frontend locale files)."""
    lang = language if language in TRANSLATIONS else DEFAULT_LANGUAGE
    text = TRANSLATIONS.get(lang, {}).get(key)
    if text is None:
        text = TRANSLATIONS[DEFAULT_LANGUAGE].get(key, key)  # last resort: the raw key itself

    if params:
        def _replace(match: re.Match) -> str:
            return str(params.get(match.group(1), match.group(0)))
        text = _PARAM_PATTERN.sub(_replace, text)
    return text