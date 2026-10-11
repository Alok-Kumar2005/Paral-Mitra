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
            "• `/lend` — List your machine for nearby farmers\n"
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
            "• `/lend` — अपनी मशीन को नज़दीकी किसानों के लिए सूचीबद्ध करें\n"
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
            "• `/lend` — ਆਪਣੀ ਮਸ਼ੀਨ ਨੇੜਲੇ ਕਿਸਾਨਾਂ ਲਈ ਸੂਚੀਬੱਧ ਕਰੋ\n"
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
    # ── Lender flow ────────────────────────────────────────────────────────────
    "lend_disclaimer": {
        "en": (
            "🧑‍🌾 *List Your Machine on Parali Mitra*\n\n"
            "ℹ️ Parali Mitra connects you with nearby farmers. "
            "Payment is agreed *directly* between you and the farmer. "
            "An administrator will verify your listing before it appears.\n\n"
            "Type /cancel at any step to stop. Ready to continue?"
        ),
        "hi": (
            "🧑‍🌾 *पराली मित्र पर अपनी मशीन सूचीबद्ध करें*\n\n"
            "ℹ️ पराली मित्र आपको नज़दीकी किसानों से जोड़ता है। "
            "भुगतान *सीधे* आप और किसान के बीच होगा। "
            "आपकी सूची दिखाई देने से पहले एक प्रशासक सत्यापित करेगा।\n\n"
            "किसी भी चरण पर /cancel टाइप करें। क्या आप जारी रखना चाहते हैं?"
        ),
        "pa": (
            "🧑‍🌾 *ਪਰਾਲੀ ਮਿੱਤਰ 'ਤੇ ਆਪਣੀ ਮਸ਼ੀਨ ਸੂਚੀਬੱਧ ਕਰੋ*\n\n"
            "ℹ️ ਪਰਾਲੀ ਮਿੱਤਰ ਤੁਹਾਨੂੰ ਨੇੜਲੇ ਕਿਸਾਨਾਂ ਨਾਲ ਜੋੜਦਾ ਹੈ। "
            "ਭੁਗਤਾਨ ਤੁਹਾਡੇ ਅਤੇ ਕਿਸਾਨ ਵਿਚਕਾਰ *ਸਿੱਧਾ* ਹੋਵੇਗਾ। "
            "ਤੁਹਾਡੀ ਸੂਚੀ ਦਿਖਣ ਤੋਂ ਪਹਿਲਾਂ ਪ੍ਰਸ਼ਾਸਕ ਦੁਆਰਾ ਜਾਂਚ ਕੀਤੀ ਜਾਵੇਗੀ।\n\n"
            "ਕਿਸੇ ਵੀ ਕਦਮ 'ਤੇ /cancel ਟਾਈਪ ਕਰੋ। ਕੀ ਤੁਸੀਂ ਜਾਰੀ ਰੱਖਣਾ ਚਾਹੁੰਦੇ ਹੋ?"
        ),
    },
    "lend_ask_contact": {
        "en": "📞 Please share your phone number using the button below, or type a 10-digit Indian mobile number:",
        "hi": "📞 कृपया नीचे बटन से अपना फ़ोन नंबर साझा करें, या 10 अंकों का मोबाइल नंबर टाइप करें:",
        "pa": "📞 ਕਿਰਪਾ ਕਰਕੇ ਹੇਠਾਂ ਬਟਨ ਤੋਂ ਆਪਣਾ ਫ਼ੋਨ ਨੰਬਰ ਸਾਂਝਾ ਕਰੋ, ਜਾਂ 10 ਅੰਕਾਂ ਦਾ ਮੋਬਾਈਲ ਨੰਬਰ ਟਾਈਪ ਕਰੋ:",
    },
    "lend_contact_wrong_user": {
        "en": "⚠️ Please share *your own* contact, not someone else's.",
        "hi": "⚠️ कृपया *अपना* संपर्क साझा करें, किसी और का नहीं।",
        "pa": "⚠️ ਕਿਰਪਾ ਕਰਕੇ *ਆਪਣਾ* ਸੰਪਰਕ ਸਾਂਝਾ ਕਰੋ, ਕਿਸੇ ਹੋਰ ਦਾ ਨਹੀਂ।",
    },
    "lend_invalid_phone": {
        "en": "⚠️ Please enter a valid 10-digit Indian mobile number (e.g. 9876543210):",
        "hi": "⚠️ कृपया एक वैध 10 अंकों का भारतीय मोबाइल नंबर दर्ज करें (जैसे 9876543210):",
        "pa": "⚠️ ਕਿਰਪਾ ਕਰਕੇ ਇੱਕ ਵੈਧ 10 ਅੰਕਾਂ ਦਾ ਭਾਰਤੀ ਮੋਬਾਈਲ ਨੰਬਰ ਦਰਜ ਕਰੋ (ਜਿਵੇਂ 9876543210):",
    },
    "lend_ask_name": {
        "en": "✍️ Enter your name or business name (2-60 characters):",
        "hi": "✍️ अपना नाम या व्यापार का नाम दर्ज करें (2-60 अक्षर):",
        "pa": "✍️ ਆਪਣਾ ਨਾਮ ਜਾਂ ਕਾਰੋਬਾਰ ਦਾ ਨਾਮ ਦਰਜ ਕਰੋ (2-60 ਅੱਖਰ):",
    },
    "lend_invalid_name": {
        "en": "⚠️ Name must be 2-60 characters. Please try again:",
        "hi": "⚠️ नाम 2-60 अक्षरों के बीच होना चाहिए। पुनः प्रयास करें:",
        "pa": "⚠️ ਨਾਮ 2-60 ਅੱਖਰਾਂ ਦੇ ਵਿਚਕਾਰ ਹੋਣਾ ਚਾਹੀਦਾ ਹੈ। ਦੁਬਾਰਾ ਕੋਸ਼ਿਸ਼ ਕਰੋ:",
    },
    "lend_ask_location": {
        "en": (
            "📍 Share your machine's base location:\n"
            "• Send a GPS pin, OR\n"
            "• Type coordinates like `30.41, 76.47`, OR\n"
            "• Type village and district (e.g. Nabha, Patiala)"
        ),
        "hi": (
            "📍 अपनी मशीन का बेस लोकेशन साझा करें:\n"
            "• GPS पिन भेजें, या\n"
            "• निर्देशांक टाइप करें जैसे `30.41, 76.47`, या\n"
            "• गाँव और जिला टाइप करें (जैसे नभा, पटियाला)"
        ),
        "pa": (
            "📍 ਆਪਣੀ ਮਸ਼ੀਨ ਦੀ ਬੇਸ ਲੋਕੇਸ਼ਨ ਸਾਂਝੀ ਕਰੋ:\n"
            "• GPS ਪਿੰਨ ਭੇਜੋ, ਜਾਂ\n"
            "• ਕੋਆਰਡੀਨੇਟ ਟਾਈਪ ਕਰੋ ਜਿਵੇਂ `30.41, 76.47`, ਜਾਂ\n"
            "• ਪਿੰਡ ਅਤੇ ਜ਼ਿਲ੍ਹਾ ਟਾਈਪ ਕਰੋ (ਜਿਵੇਂ ਨਭਾ, ਪਟਿਆਲਾ)"
        ),
    },
    "lend_location_failed": {
        "en": "❌ Could not find that location. Please try again with a GPS pin, coordinates, or a specific village and district:",
        "hi": "❌ वह स्थान नहीं मिला। कृपया GPS पिन, निर्देशांक, या गाँव और जिला पुनः दर्ज करें:",
        "pa": "❌ ਉਹ ਸਥਾਨ ਨਹੀਂ ਮਿਲਿਆ। ਕਿਰਪਾ ਕਰਕੇ GPS ਪਿੰਨ, ਕੋਆਰਡੀਨੇਟ, ਜਾਂ ਪਿੰਡ ਅਤੇ ਜ਼ਿਲ੍ਹਾ ਦੁਬਾਰਾ ਦਰਜ ਕਰੋ:",
    },
    "lend_location_outside_india": {
        "en": "⚠️ That location appears to be outside our service area (Punjab/Haryana/UP). Please try again:",
        "hi": "⚠️ वह स्थान हमारे सेवा क्षेत्र (पंजाब/हरियाणा/UP) से बाहर लगता है। कृपया पुनः प्रयास करें:",
        "pa": "⚠️ ਉਹ ਸਥਾਨ ਸਾਡੇ ਸੇਵਾ ਖੇਤਰ (ਪੰਜਾਬ/ਹਰਿਆਣਾ/UP) ਤੋਂ ਬਾਹਰ ਲੱਗਦਾ ਹੈ। ਕਿਰਪਾ ਕਰਕੇ ਦੁਬਾਰਾ ਕੋਸ਼ਿਸ਼ ਕਰੋ:",
    },
    "lend_ask_district_state": {
        "en": "📍 The geocoder did not return a district/state. Please type your district and state (e.g. Patiala, Punjab):",
        "hi": "📍 जिला/राज्य नहीं मिला। कृपया अपना जिला और राज्य टाइप करें (जैसे पटियाला, पंजाब):",
        "pa": "📍 ਜ਼ਿਲ੍ਹਾ/ਰਾਜ ਨਹੀਂ ਮਿਲਿਆ। ਕਿਰਪਾ ਕਰਕੇ ਆਪਣਾ ਜ਼ਿਲ੍ਹਾ ਅਤੇ ਰਾਜ ਟਾਈਪ ਕਰੋ (ਜਿਵੇਂ ਪਟਿਆਲਾ, ਪੰਜਾਬ):",
    },
    "lend_ask_machine_type": {
        "en": "🚜 Select the type of machine you are offering:",
        "hi": "🚜 वह मशीन का प्रकार चुनें जो आप प्रदान करना चाहते हैं:",
        "pa": "🚜 ਉਹ ਮਸ਼ੀਨ ਦੀ ਕਿਸਮ ਚੁਣੋ ਜੋ ਤੁਸੀਂ ਦੇਣਾ ਚਾਹੁੰਦੇ ਹੋ:",
    },
    "lend_ask_rate": {
        "en": "💰 Enter your rate per acre in INR (e.g. 1500):",
        "hi": "💰 प्रति एकड़ किराया INR में दर्ज करें (जैसे 1500):",
        "pa": "💰 ਪ੍ਰਤੀ ਏਕੜ ਕਿਰਾਇਆ INR ਵਿੱਚ ਦਰਜ ਕਰੋ (ਜਿਵੇਂ 1500):",
    },
    "lend_invalid_rate": {
        "en": "⚠️ Please enter a valid rate (e.g. 1500). Rate must be between ₹{lo} and ₹{hi} per acre:",
        "hi": "⚠️ कृपया वैध किराया दर्ज करें (जैसे 1500)। दर ₹{lo} से ₹{hi} प्रति एकड़ के बीच होनी चाहिए:",
        "pa": "⚠️ ਕਿਰਪਾ ਕਰਕੇ ਵੈਧ ਕਿਰਾਇਆ ਦਰਜ ਕਰੋ (ਜਿਵੇਂ 1500)। ਦਰ ₹{lo} ਤੋਂ ₹{hi} ਪ੍ਰਤੀ ਏਕੜ ਵਿਚਕਾਰ ਹੋਣੀ ਚਾਹੀਦੀ ਹੈ:",
    },
    "lend_ask_travel": {
        "en": "🚗 Enter your travel charge per km in INR (0 to 1000, e.g. 10). Enter 0 if included in rate:",
        "hi": "🚗 प्रति किमी यात्रा शुल्क INR में दर्ज करें (0 से 1000, जैसे 10)। यदि किराये में शामिल है तो 0 दर्ज करें:",
        "pa": "🚗 ਪ੍ਰਤੀ ਕਿਲੋਮੀਟਰ ਯਾਤਰਾ ਖਰਚ INR ਵਿੱਚ ਦਰਜ ਕਰੋ (0 ਤੋਂ 1000, ਜਿਵੇਂ 10):",
    },
    "lend_invalid_travel": {
        "en": "⚠️ Travel charge must be between 0 and 1000 INR/km. Please try again:",
        "hi": "⚠️ यात्रा शुल्क 0 से 1000 INR/km के बीच होना चाहिए। पुनः प्रयास करें:",
        "pa": "⚠️ ਯਾਤਰਾ ਖਰਚ 0 ਤੋਂ 1000 INR/km ਵਿਚਕਾਰ ਹੋਣਾ ਚਾਹੀਦਾ ਹੈ। ਦੁਬਾਰਾ ਕੋਸ਼ਿਸ਼ ਕਰੋ:",
    },
    "lend_ask_radius": {
        "en": "📏 Enter how far you are willing to travel in km (1 to 100, e.g. 20):",
        "hi": "📏 बताएं आप कितने किमी तक जाने को तैयार हैं (1 से 100, जैसे 20):",
        "pa": "📏 ਦੱਸੋ ਤੁਸੀਂ ਕਿੰਨੇ ਕਿਲੋਮੀਟਰ ਤੱਕ ਜਾਣ ਲਈ ਤਿਆਰ ਹੋ (1 ਤੋਂ 100, ਜਿਵੇਂ 20):",
    },
    "lend_invalid_radius": {
        "en": "⚠️ Radius must be between 1 and 100 km. Please try again:",
        "hi": "⚠️ त्रिज्या 1 से 100 km के बीच होनी चाहिए। पुनः प्रयास करें:",
        "pa": "⚠️ ਰੇਡੀਅਸ 1 ਤੋਂ 100 km ਵਿਚਕਾਰ ਹੋਣਾ ਚਾਹੀਦਾ ਹੈ। ਦੁਬਾਰਾ ਕੋਸ਼ਿਸ਼ ਕਰੋ:",
    },
    "lend_ask_terms": {
        "en": (
            "📝 *Optional:* Add a short terms note (max 160 chars) — e.g. 'Rate includes tractor and driver; farmer pays diesel.'\n"
            "Type your note or send /skip to leave blank:"
        ),
        "hi": (
            "📝 *वैकल्पिक:* एक छोटी शर्तों की नोट लिखें (अधिकतम 160 अक्षर) — जैसे 'किराये में ट्रैक्टर और ड्राइवर शामिल है; किसान डीज़ल देगा।'\n"
            "नोट टाइप करें या /skip लिखकर खाली छोड़ें:"
        ),
        "pa": (
            "📝 *ਵਿਕਲਪਿਕ:* ਛੋਟੀ ਸ਼ਰਤਾਂ ਦੀ ਨੋਟ ਲਿਖੋ (ਵੱਧ ਤੋਂ ਵੱਧ 160 ਅੱਖਰ) — ਜਿਵੇਂ 'ਕਿਰਾਏ ਵਿੱਚ ਟਰੈਕਟਰ ਅਤੇ ਡਰਾਈਵਰ ਸ਼ਾਮਲ ਹੈ; ਕਿਸਾਨ ਡੀਜ਼ਲ ਦੇਵੇਗਾ।'\n"
            "ਨੋਟ ਟਾਈਪ ਕਰੋ ਜਾਂ /skip ਲਿਖ ਕੇ ਖਾਲੀ ਛੱਡੋ:"
        ),
    },
    "lend_success": {
        "en": (
            "✅ *Lender Registration Submitted!*\n\n"
            "Provider ID: `{provider_id}`\n"
            "Machine: *{machine_type}*\n"
            "Rate: *₹{rate}/acre*\n"
            "District: *{district}*\n"
            "Status: ⏳ *PENDING — Admin will verify before you appear*\n\n"
            "You will be notified once approved. Use /mymachines and /mybookings to manage your listing."
        ),
        "hi": (
            "✅ *लेंडर पंजीकरण जमा हो गया!*\n\n"
            "Provider ID: `{provider_id}`\n"
            "मशीन: *{machine_type}*\n"
            "किराया: *₹{rate}/एकड़*\n"
            "जिला: *{district}*\n"
            "स्थिति: ⏳ *लंबित — दिखाई देने से पहले एडमिन सत्यापित करेगा*\n\n"
            "स्वीकृत होने पर आपको सूचित किया जाएगा। /mymachines और /mybookings से प्रबंधित करें।"
        ),
        "pa": (
            "✅ *ਲੈਂਡਰ ਰਜਿਸਟ੍ਰੇਸ਼ਨ ਜਮ੍ਹਾ ਹੋ ਗਈ!*\n\n"
            "Provider ID: `{provider_id}`\n"
            "ਮਸ਼ੀਨ: *{machine_type}*\n"
            "ਕਿਰਾਇਆ: *₹{rate}/ਏਕੜ*\n"
            "ਜ਼ਿਲ੍ਹਾ: *{district}*\n"
            "ਸਥਿਤੀ: ⏳ *ਲੰਬਿਤ — ਦਿਖਾਈ ਦੇਣ ਤੋਂ ਪਹਿਲਾਂ ਐਡਮਿਨ ਜਾਂਚ ਕਰੇਗਾ*\n\n"
            "ਮਨਜ਼ੂਰੀ ਮਿਲਣ 'ਤੇ ਤੁਹਾਨੂੰ ਸੂਚਿਤ ਕੀਤਾ ਜਾਵੇਗਾ। /mymachines ਅਤੇ /mybookings ਨਾਲ ਪ੍ਰਬੰਧਿਤ ਕਰੋ।"
        ),
    },
    "lend_already_registered": {
        "en": "ℹ️ You are already registered as a provider. Use /mymachines or /mybookings to manage your account.",
        "hi": "ℹ️ आप पहले से ही एक प्रदाता के रूप में पंजीकृत हैं। /mymachines या /mybookings से अपना खाता प्रबंधित करें।",
        "pa": "ℹ️ ਤੁਸੀਂ ਪਹਿਲਾਂ ਹੀ ਪ੍ਰਦਾਤਾ ਵਜੋਂ ਰਜਿਸਟਰ ਹੋ। /mymachines ਜਾਂ /mybookings ਨਾਲ ਆਪਣਾ ਖਾਤਾ ਪ੍ਰਬੰਧਿਤ ਕਰੋ।",
    },
    "lend_cancelled": {
        "en": "❌ Lender registration cancelled. Type /lend to start again or /help for other commands.",
        "hi": "❌ लेंडर पंजीकरण रद्द। दोबारा शुरू करने के लिए /lend टाइप करें या /help देखें।",
        "pa": "❌ ਲੈਂਡਰ ਰਜਿਸਟ੍ਰੇਸ਼ਨ ਰੱਦ। ਦੁਬਾਰਾ ਸ਼ੁਰੂ ਕਰਨ ਲਈ /lend ਟਾਈਪ ਕਰੋ ਜਾਂ /help ਵੇਖੋ।",
    },
    "lend_duplicate_phone": {
        "en": "⚠️ That phone number is already registered with another provider. Please use a different number:",
        "hi": "⚠️ वह फ़ोन नंबर पहले से किसी अन्य प्रदाता के साथ पंजीकृत है। कृपया दूसरा नंबर उपयोग करें:",
        "pa": "⚠️ ਉਹ ਫ਼ੋਨ ਨੰਬਰ ਪਹਿਲਾਂ ਹੀ ਕਿਸੇ ਹੋਰ ਪ੍ਰਦਾਤਾ ਨਾਲ ਰਜਿਸਟਰ ਹੈ। ਕਿਰਪਾ ਕਰਕੇ ਵੱਖਰਾ ਨੰਬਰ ਵਰਤੋ:",
    },
    "lend_share_contact_btn": {
        "en": "📞 Share My Phone Number",
        "hi": "📞 मेरा फ़ोन नंबर साझा करें",
        "pa": "📞 ਮੇਰਾ ਫ਼ੋਨ ਨੰਬਰ ਸਾਂਝਾ ਕਰੋ",
    },
    "lender_payment_footer": {
        "en": "💡 Payment is agreed directly with the owner.",
        "hi": "💡 भुगतान सीधे मालिक के साथ तय होता है।",
        "pa": "💡 ਭੁਗਤਾਨ ਸਿੱਧਾ ਮਾਲਕ ਨਾਲ ਤੈਅ ਹੁੰਦਾ ਹੈ।",
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
