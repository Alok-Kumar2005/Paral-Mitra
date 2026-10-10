"""Internationalization (i18n) module for Parali Mitra.

Supports English (en), Hindi (hi), and Punjabi (pa).
Fallback language is English.
"""

from __future__ import annotations

from typing import Any

STRINGS: dict[str, dict[str, str]] = {
    "welcome": {
        "en": (
            "🌾 *Welcome to Parali Mitra (पराली मित्र)!*\n\n"
            "I help paddy farmers in Punjab & Haryana clear crop residue without burning — "
            "saving you money, avoiding fines, and connecting you to nearby Custom Hiring Centres (CHCs) "
            "and commercial biomass buyers.\n\n"
            "📍 *To get started, please share your farm location pin or type your village & district name.*"
        ),
        "hi": (
            "🌾 *पराली मित्र (Parali Mitra) में आपका स्वागत है!*\n\n"
            "मैं पंजाब और हरियाणा के किसान भाइयों को बिना पराली जलाए अगली फसल बोने में मदद करता हूँ — "
            "ताकि आपका खर्च बचे, जुर्माना न लगे और आपको नजदीकी मशीनें (CHC) और पराली खरीदार मिल सकें।\n\n"
            "📍 *शुरू करने के लिए कृपया अपने खेत की लोकेशन साझा करें या अपने गाँव और जिले का नाम लिखें।*"
        ),
        "pa": (
            "🌾 *ਪਰਾਲੀ ਮਿੱਤਰ (Parali Mitra) ਵਿੱਚ ਤੁਹਾਡਾ ਸੁਆਗਤ ਹੈ!*\n\n"
            "ਮੈਂ ਪੰਜਾਬ ਅਤੇ ਹਰਿਆਣਾ ਦੇ ਕਿਸਾਨ ਵੀਰਾਂ ਨੂੰ ਬਿਨਾਂ ਪਰਾਲੀ ਸਾੜੇ ਕਣਕ ਬੀਜਣ ਵਿੱਚ ਮਦਦ ਕਰਦਾ ਹਾਂ — "
            "ਤਾਂ ਜੋ ਤੁਹਾਡਾ ਖਰਚਾ ਬਚੇ, ਜੁਰਮਾਨਾ ਨਾ ਲੱਗੇ ਅਤੇ ਨੇੜਲੀਆਂ ਮਸ਼ੀਨਾਂ (CHC) ਅਤੇ ਪਰਾਲੀ ਖਰੀਦਦਾਰ ਮਿਲ ਸਕਣ।\n\n"
            "📍 *ਸ਼ੁਰੂ ਕਰਨ ਲਈ ਕਿਰਪਾ ਕਰਕੇ ਆਪਣੇ ਖੇਤ ਦੀ ਲੋਕੇਸ਼ਨ ਸਾਂਝੀ ਕਰੋ ਜਾਂ ਆਪਣੇ ਪਿੰਡ ਤੇ ਜ਼ਿਲ੍ਹੇ ਦਾ ਨਾਮ ਲਿਖੋ।*"
        ),
    },
    "help": {
        "en": (
            "📖 *Parali Mitra Commands:*\n\n"
            "• `/start` — Restart and set your language preference\n"
            "• `/options` — Calculate ranked residue solutions (costs & deadlines)\n"
            "• `/machines` — Browse nearby verified machinery and rates\n"
            "• `/mybookings` — Check status of your requested bookings\n"
            "• `/reset` — Clear current farm details and start over\n"
            "• `/forget_me` — Delete all your stored data (GDPR/Privacy)\n"
            "• `/owner` — CHC and Buyer operator portal\n"
            "• `/help` — Show this guide"
        ),
        "hi": (
            "📖 *पराली मित्र के मुख्य निर्देश:*\n\n"
            "• `/start` — भाषा चुनें और नई शुरुआत करें\n"
            "• `/options` — पराली प्रबंधन के सबसे सस्ते व समयबद्ध विकल्प देखें\n"
            "• `/machines` — नजदीकी सत्यापित मशीनें और उनके किराये देखें\n"
            "• `/mybookings` — अपनी बुकिंग की स्थिति जांचें\n"
            "• `/reset` — खेती का विवरण दोबारा भरें\n"
            "• `/forget_me` — अपना सारा डाटा सिस्टम से हटाएं\n"
            "• `/owner` — मशीन मालिकों व खरीदारों के लिए पोर्टल\n"
            "• `/help` — सहायता संदेश देखें"
        ),
        "pa": (
            "📖 *ਪਰਾਲੀ ਮਿੱਤਰ ਦੀਆਂ ਮੁੱਖ ਕਮਾਂਡਾਂ:*\n\n"
            "• `/start` — ਭਾਸ਼ਾ ਚੁਣੋ ਅਤੇ ਨਵੀਂ ਸ਼ੁਰੂਆਤ ਕਰੋ\n"
            "• `/options` — ਪਰਾਲੀ ਸਾਂਭਣ ਦੇ ਸਭ ਤੋਂ ਸਸਤੇ ਤੇ ਵਧੀਆ ਵਿਕਲਪ ਵੇਖੋ\n"
            "• `/machines` — ਨੇੜਲੀਆਂ ਮਸ਼ੀਨਾਂ ਅਤੇ ਕਿਰਾਏ ਵੇਖੋ\n"
            "• `/mybookings` — ਆਪਣੀ ਬੁਕਿੰਗ ਦੀ ਸਥਿਤੀ ਵੇਖੋ\n"
            "• `/reset` — ਨਵੀਂ ਸ਼ੁਰੂਆਤ ਕਰੋ\n"
            "• `/forget_me` — ਆਪਣਾ ਸਾਰਾ ਡਾਟਾ ਹਟਾਓ\n"
            "• `/owner` — ਮਸ਼ੀਨ ਮਾਲਕਾਂ ਲਈ ਪੋਰਟਲ\n"
            "• `/help` — ਮਦਦ ਸੁਨੇਹਾ ਵੇਖੋ"
        ),
    },
    "lang_selected": {
        "en": "Language set to English 🇬🇧. You can now chat or type /options.",
        "hi": "भाषा हिन्दी 🇮🇳 चुन ली गई है। आप बातचीत शुरू कर सकते हैं या /options लिख सकते हैं।",
        "pa": "ਭਾਸ਼ਾ ਪੰਜਾਬੀ 🌾 ਚੁਣ ਲਈ ਗਈ ਹੈ। ਤੁਸੀਂ ਗੱਲਬਾਤ ਸ਼ੁਰੂ ਕਰ ਸਕਦੇ ਹੋ ਜਾਂ /options ਲਿਖ ਸਕਦੇ ਹੋ।",
    },
    "share_location_btn": {
        "en": "📍 Share My Farm Location",
        "hi": "📍 अपने खेत का स्थान साझा करें",
        "pa": "📍 ਆਪਣੇ ਖੇਤ ਦਾ ਸਥਾਨ ਸਾਂਝਾ ਕਰੋ",
    },
    "location_saved": {
        "en": "✅ Location saved: *{location}*. How many acres of paddy do you have?",
        "hi": "✅ स्थान दर्ज हो गया: *{location}*। आपके पास कितने एकड़ धान का खेत है?",
        "pa": "✅ ਸਥਾਨ ਦਰਜ ਹੋ ਗਿਆ: *{location}*। ਤੁਹਾਡੇ ਕੋਲ ਕਿੰਨੇ ਏਕੜ ਝੋਨਾ ਹੈ?",
    },
    "no_bookings": {
        "en": "You have no active bookings. Type /options to evaluate solutions or /machines to browse nearby equipment.",
        "hi": "आपकी कोई सक्रिय बुकिंग नहीं है। विकल्प देखने के लिए /options या मशीनें देखने के लिए /machines लिखें।",
        "pa": "ਤੁਹਾਡੀ ਕੋਈ ਬੁਕਿੰਗ ਨਹੀਂ ਹੈ। ਵਿਕਲਪ ਵੇਖਣ ਲਈ /options ਜਾਂ ਮਸ਼ੀਨਾਂ ਵੇਖਣ ਲਈ /machines ਲਿਖੋ।",
    },
    "mybookings_header": {
        "en": "📋 *Your Parali Mitra Bookings:*",
        "hi": "📋 *आपकी पराली मित्र बुकिंग:*",
        "pa": "📋 *ਤੁਹਾਡੀਆਂ ਪਰਾਲੀ ਮਿੱਤਰ ਬੁਕਿੰਗਾਂ:*",
    },
    "nearby_machines_header": {
        "en": "🚜 *Verified Agricultural Machinery Near You (Within {radius_km} km):*",
        "hi": "🚜 *आपके नजदीकी सत्यापित कृषि यंत्र ({radius_km} किमी के दायरे में):*",
        "pa": "🚜 *ਤੁਹਾਡੇ ਨੇੜਲੀਆਂ ਪ੍ਰਮਾਣਿਤ ਖੇਤੀ ਮਸ਼ੀਨਾਂ ({radius_km} ਕਿਲੋਮੀਟਰ ਦੇ ਦਾਇਰੇ ਵਿੱਚ):*",
    },
    "no_nearby_machines": {
        "en": "No active machines found within {radius_km} km. Please type /options to explore regional options.",
        "hi": "{radius_km} किमी के दायरे में कोई मशीन उपलब्ध नहीं मिली। कृपया /options लिखकर अन्य विकल्प देखें।",
        "pa": "{radius_km} ਕਿਲੋਮੀਟਰ ਦੇ ਦਾਇਰੇ ਵਿੱਚ ਕੋਈ ਮਸ਼ੀਨ ਨਹੀਂ ਮਿਲੀ। ਕਿਰਪਾ ਕਰਕੇ /options ਲਿਖ ਕੇ ਹੋਰ ਵਿਕਲਪ ਵੇਖੋ।",
    },
    "booking_success_farmer": {
        "en": (
            "📋 *Booking Request Created!*\n\n"
            "Booking ID: `{booking_id}`\n"
            "Target: *{target_name}*\n"
            "Area: *{acres} acres*\n"
            "Date: *{requested_date}*\n"
            "Status: ⏳ *PENDING (Operator Notified)*\n\n"
            "The operator has up to 48 hours to confirm your request."
        ),
        "hi": (
            "📋 *बुकिंग अनुरोध भेजा गया!*\n\n"
            "बुकिंग ID: `{booking_id}`\n"
            "उपकरण/खरीदार: *{target_name}*\n"
            "रकबा: *{acres} एकड़*\n"
            "तारीख: *{requested_date}*\n"
            "स्थिति: ⏳ *लंबित (ऑपरेटर को सूचित कर दिया गया है)*\n\n"
            "ऑपरेटर 48 घंटे के भीतर आपकी बुकिंग की पुष्टि करेंगे।"
        ),
        "pa": (
            "📋 *ਬੁਕਿੰਗ ਬੇਨਤੀ ਭੇਜੀ ਗਈ!*\n\n"
            "ਬੁਕਿੰਗ ID: `{booking_id}`\n"
            "ਮਸ਼ੀਨ/ਖਰੀਦਦਾਰ: *{target_name}*\n"
            "ਰਕਬਾ: *{acres} ਏਕੜ*\n"
            "ਮਿਤੀ: *{requested_date}*\n"
            "ਸਥਿਤੀ: ⏳ *ਲੰਬਿਤ (ਓਪਰੇਟਰ ਨੂੰ ਸੂਚਿਤ ਕਰ ਦਿੱਤਾ ਗਿਆ ਹੈ)*\n\n"
            "ਓਪਰੇਟਰ 48 ਘੰਟਿਆਂ ਦੇ ਅੰਦਰ ਤੁਹਾਡੀ ਬੁਕਿੰਗ ਦੀ ਪੁਸ਼ਟੀ ਕਰੇਗਾ।"
        ),
    },
    "owner_portal_title": {
        "en": "👨‍🌾 *CHC & Commercial Buyer Operator Portal*",
        "hi": "👨‍🌾 *मशीन मालिक (CHC) व पराली खरीदार पोर्टल*",
        "pa": "👨‍🌾 *ਮਸ਼ੀਨ ਮਾਲਕ (CHC) ਤੇ ਪਰਾਲੀ ਖਰੀਦਦਾਰ ਪੋਰਟਲ*",
    },
    "owner_enter_passcode": {
        "en": "Please enter the operator passcode to access the management portal:",
        "hi": "प्रबंधन पोर्टल में प्रवेश करने के लिए कृपया ऑपरेटर पासकोड दर्ज करें:",
        "pa": "ਪੋਰਟਲ ਵਿੱਚ ਦਾਖਲ ਹੋਣ ਲਈ ਕਿਰਪਾ ਕਰਕੇ ਓਪਰੇਟਰ ਪਾਸਕੋਡ ਦਰਜ ਕਰੋ:",
    },
    "owner_invalid_passcode": {
        "en": "❌ Incorrect passcode. Please try again.",
        "hi": "❌ गलत पासकोड। कृपया पुनः प्रयास करें।",
        "pa": "❌ ਗਲਤ ਪਾਸਕੋਡ। ਕਿਰਪਾ ਕਰਕੇ ਦੁਬਾਰਾ ਕੋਸ਼ਿਸ਼ ਕਰੋ।",
    },
    "owner_locked_out": {
        "en": "⛔ Too many incorrect attempts. You are locked out for {mins} minutes.",
        "hi": "⛔ कई बार गलत पासकोड दर्ज किया गया। आप {mins} मिनट के लिए लॉक हैं।",
        "pa": "⛔ ਬਹੁਤ ਸਾਰੀਆਂ ਗਲਤ ਕੋਸ਼ਿਸ਼ਾਂ। ਤੁਸੀਂ {mins} ਮਿੰਟਾਂ ਲਈ ਲੌਕ ਹੋ।",
    },
    "admin_only": {
        "en": "⛔ This action is restricted to verified administrators.",
        "hi": "⛔ यह क्रिया केवल अधिकृत प्रशासक (Admin) के लिए है।",
        "pa": "⛔ ਇਹ ਕਾਰਵਾਈ ਸਿਰਫ਼ ਪ੍ਰਸ਼ਾਸਕ (Admin) ਲਈ ਹੈ।",
    },
    "fire_alert": {
        "en": "🔥 Active fire hotspot detected near your farm ({lat}, {lon}) covering {area}. Please do not burn residue!",
        "hi": "🔥 आपके खेत के पास सक्रिय आग ({lat}, {lon}) का पता चला है ({area})। कृपया पराली न जलाएं!",
        "pa": "🔥 ਤੁਹਾਡੇ ਖੇਤ ਨੇੜੇ ਅੱਗ ({lat}, {lon}) ਦਾ ਪਤਾ ਲੱਗਾ ਹੈ ({area})। ਕਿਰਪਾ ਕਰਕੇ ਪਰਾਲੀ ਨਾ ਸਾੜੋ!",
    },
    "service_waking_up": {
        "en": "⏳ The Parali Mitra database is waking up. Please try again in 5 seconds.",
        "hi": "⏳ पराली मित्र डेटाबेस सक्रिय हो रहा है। कृपया 5 सेकंड में पुनः प्रयास करें।",
        "pa": "⏳ ਪਰਾਲੀ ਮਿੱਤਰ ਡਾਟਾਬੇਸ ਸਰਗਰਮ ਹੋ ਰਿਹਾ ਹੈ। ਕਿਰਪਾ ਕਰਕੇ 5 ਸਕਿੰਟਾਂ ਵਿੱਚ ਦੁਬਾਰਾ ਕੋਸ਼ਿਸ਼ ਕਰੋ।",
    },
    "data_forgotten": {
        "en": "🗑️ All your data has been permanently deleted from Parali Mitra. Send /start to begin afresh.",
        "hi": "🗑️ आपकी सारी जानकारी पराली मित्र से पूरी तरह हटा दी गई है। दोबारा शुरू करने के लिए /start भेजें।",
        "pa": "🗑️ ਤੁਹਾਡੀ ਸਾਰੀ ਜਾਣਕਾਰੀ ਪਰਾਲੀ ਮਿੱਤਰ ਤੋਂ ਹਟਾ ਦਿੱਤੀ ਗਈ ਹੈ। ਦੁਬਾਰਾ ਸ਼ੁਰੂ ਕਰਨ ਲਈ /start ਭੇਜੋ।",
    },
}


def t(key: str, lang: str = "hi", **kwargs: Any) -> str:
    """Retrieve localized string with formatting and graceful fallback to English."""
    lang_map = STRINGS.get(key, {})
    template = lang_map.get(lang) or lang_map.get("en") or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except Exception:
            return template
    return template
