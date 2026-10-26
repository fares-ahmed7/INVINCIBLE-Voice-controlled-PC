"""
Website whitelist shared by the AI fast path and the executor.

The model never supplies a URL: it only picks one of these site names, and the executor
opens the fixed URL below. The domain can never come from speech/model output.
"""

SITES = {
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "facebook": "https://www.facebook.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "whatsapp": "https://web.whatsapp.com",
    "wikipedia": "https://www.wikipedia.org",
}

SEARCH_URLS = {
    "google": "https://www.google.com/search?q=",
    "youtube": "https://www.youtube.com/results?search_query=",
}

# Spoken names (Arabic/English) -> canonical site key. Normalized before matching.
SITE_ALIASES = {
    "google": "google",
    "جوجل": "google",
    "جوجل دوت كوم": "google",
    "youtube": "youtube",
    "يوتيوب": "youtube",
    "يو تيوب": "youtube",
    "facebook": "facebook",
    "فيسبوك": "facebook",
    "فيس بوك": "facebook",
    "gmail": "gmail",
    "جيميل": "gmail",
    "جي ميل": "gmail",
    "github": "github",
    "جيت هاب": "github",
    "جيتهاب": "github",
    "whatsapp": "whatsapp",
    "واتساب": "whatsapp",
    "واتس اب": "whatsapp",
    "wikipedia": "wikipedia",
    "ويكيبيديا": "wikipedia",
}
