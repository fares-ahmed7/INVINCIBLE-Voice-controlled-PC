"""
App registry: the manual override layer (Windows-only).

name -> (Windows target, Start-Menu keyword)

- Windows target: an exe name ("chrome.exe", "calc.exe") or a URI scheme ("discord:").
- Start-Menu keyword: if the target fails, we search your Start Menu shortcuts for this word.
All of these are written here by us. The model only picks a NAME.
"""
APPS = {
    "chrome":       ("chrome.exe",     "chrome"),
    "firefox":      ("firefox.exe",    "firefox"),
    "edge":         ("msedge.exe",     "edge"),
    "calculator":   ("calc.exe",       "calculator"),
    "terminal":     ("cmd.exe",        "command prompt"),
    "files":        ("explorer.exe",   "file explorer"),
    "text_editor":  ("notepad.exe",    "notepad"),
    "notepad":      ("notepad.exe",    "notepad"),
    "notepad++":    ("notepad++.exe",  "notepad++"),
    "paint":        ("mspaint.exe",    "paint"),
    "task_manager": ("taskmgr.exe",    "task manager"),
    "settings":     ("ms-settings:",   "settings"),
    "discord":      ("discord:",       "discord"),
    "spotify":      ("spotify:",       "spotify"),
    "whatsapp":     ("whatsapp:",      "whatsapp"),
    "telegram":     ("tg:",            "telegram"),
    "vscode":       ("code.exe",       "visual studio code"),
    "word":         ("winword.exe",    "word"),
    "excel":        ("excel.exe",      "excel"),
    "powerpoint":   ("powerpnt.exe",   "powerpoint"),
}
APP_NAMES = list(APPS)
BROWSER_NAMES = ["chrome", "edge", "firefox"]

# Manual alias layer: spoken/Arabic/STT-friendly name -> canonical app name or a
# discovery keyword (e.g. "فوتوشوب" -> "photoshop" finds the installed shortcut).
# Manual entries win over auto-discovered Start Menu shortcuts.
ALIASES = {
    "كروم": "chrome",
    "جوجل كروم": "chrome",
    "قوقل كروم": "chrome",
    "اوبن كروم": "chrome",
    "google chrome": "chrome",
    "فايرفوكس": "firefox",
    "فاير فوكس": "firefox",
    "mozilla firefox": "firefox",
    "ايدج": "edge",
    "إيدج": "edge",
    "microsoft edge": "edge",
    "الحاسبة": "calculator",
    "الآلة الحاسبة": "calculator",
    "كالكيوليتور": "calculator",
    "calc": "calculator",
    "الترمنال": "terminal",
    "التيرمنال": "terminal",
    "command prompt": "terminal",
    "الملفات": "files",
    "مستكشف الملفات": "files",
    "file explorer": "files",
    "محرر النصوص": "text_editor",
    "text editor": "text_editor",
    "الرسام": "paint",
    "مدير المهام": "task_manager",
    "task manager": "task_manager",
    "الاعدادات": "settings",
    "الإعدادات": "settings",
    "ديسكورد": "discord",
    "سبوتيفاي": "spotify",
    "سبوتي فاي": "spotify",
    "واتساب": "whatsapp",
    "تليجرام": "telegram",
    "فيس كود": "vscode",
    "vs code": "vscode",
    "visual studio code": "vscode",
    "وورد": "word",
    "microsoft word": "word",
    "اكسل": "excel",
    "microsoft excel": "excel",
    "بوربوينت": "powerpoint",
    "microsoft powerpoint": "powerpoint",
    "فوتوشوب": "photoshop",
    "فوتو شوب": "photoshop",
    "adobe photoshop": "photoshop",
    "نوت باد": "notepad",
    "نوتباد": "notepad",
    "notepad plus plus": "notepad++",
}
