"""Telegram keyboard layouts (inline and reply markups) for Parali Mitra."""

from __future__ import annotations

from typing import Any

# ── Multilingual UI strings ───────────────────────────────────────────────────

TEXTS = {
    "share_location_btn": {
        "en": "📍 Share My Farm Location",
        "hi": "📍 अपने खेत का स्थान साझा करें",
        "pa": "📍 ਆਪਣੇ ਖੇਤ ਦਾ ਸਥਾਨ ਸਾਂਝਾ ਕਰੋ",
    },
    "book_btn_prefix": {
        "en": "Book Option",
        "hi": "विकल्प बुक करें",
        "pa": "ਵਿਕਲਪ ਬੁੱਕ ਕਰੋ",
    },
    "confirm_btn": {
        "en": "✅ Confirm Booking",
        "hi": "✅ बुकिंग पक्की करें",
        "pa": "✅ ਬੁਕਿੰਗ ਪੱਕੀ ਕਰੋ",
    },
    "cancel_btn": {
        "en": "❌ Cancel",
        "hi": "❌ रद्द करें",
        "pa": "❌ ਰੱਦ ਕਰੋ",
    },
}


def get_language_keyboard() -> dict[str, Any]:
    """Inline keyboard for initial language selection."""
    return {
        "inline_keyboard": [
            [
                {"text": "🇬🇧 English", "callback_data": "lang:en"},
                {"text": "🇮🇳 हिन्दी", "callback_data": "lang:hi"},
                {"text": "🌾 ਪੰਜਾਬੀ", "callback_data": "lang:pa"},
            ]
        ]
    }


def get_location_keyboard(lang: str = "hi") -> dict[str, Any]:
    """One-tap reply keyboard requesting farmer's GPS location pin."""
    btn_text = TEXTS["share_location_btn"].get(lang, TEXTS["share_location_btn"]["hi"])
    return {
        "keyboard": [
            [{"text": btn_text, "request_location": True}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }


def get_remove_keyboard() -> dict[str, Any]:
    """Hides active custom reply keyboard."""
    return {"remove_keyboard": True}


def get_options_keyboard(
    options: list[dict[str, Any]],
    lang: str = "hi",
) -> dict[str, Any]:
    """Generates inline buttons for ranked residue management options."""
    buttons: list[list[dict[str, str]]] = []

    for idx, opt in enumerate(options):
        name = (
            opt.get("target_name")
            or opt.get("display_name")
            or opt.get("machine_type")
            or opt.get("buyer_type")
            or opt.get("category")
            or f"Option {idx + 1}"
        )
        net_cost = opt.get("net_cost", 0)
        cost_str = f"₹{abs(int(net_cost)):,}"
        if net_cost < 0:
            cost_label = f"+{cost_str} (Profit)"
        else:
            cost_label = f"-{cost_str}"

        short_name = name[:30] + "…" if len(name) > 30 else name
        btn_text = f"🚜 #{idx + 1} {short_name} [{cost_label}]"
        cb_data = f"book_opt:{idx}"
        buttons.append([{"text": btn_text, "callback_data": cb_data}])

    return {"inline_keyboard": buttons}


def get_booking_confirm_keyboard(
    option_idx: int,
    lang: str = "hi",
) -> dict[str, Any]:
    """Inline keyboard confirming a specific option booking."""
    confirm_text = TEXTS["confirm_btn"].get(lang, TEXTS["confirm_btn"]["hi"])
    cancel_text = TEXTS["cancel_btn"].get(lang, TEXTS["cancel_btn"]["hi"])
    return {
        "inline_keyboard": [
            [
                {"text": confirm_text, "callback_data": f"confirm_book:{option_idx}"},
                {"text": cancel_text, "callback_data": "cancel_book"},
            ]
        ]
    }
