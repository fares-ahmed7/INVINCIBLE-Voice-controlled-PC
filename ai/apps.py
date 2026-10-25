"""
App registry: THE ONLY PLACE you edit to add a new app.
name -> (Windows target, Linux command, Start-Menu keyword)

- Windows target: an exe name registered in Windows ("chrome", "calc.exe") or a URI ("discord:").
- Start-Menu keyword: if the target fails, we search your Start Menu shortcuts for this word.
All of these are written here by us. The model only picks a NAME.
"""
APPS = {
    "chrome":       ("chrome",       ["google-chrome"],        "chrome"),
    "firefox":      ("firefox",      ["firefox"],              "firefox"),
    "edge":         ("msedge",       ["microsoft-edge"],       "edge"),
    "calculator":   ("calc.exe",     ["gnome-calculator"],     "calculator"),
    "terminal":     ("cmd.exe",      ["gnome-terminal"],       "command prompt"),
    "files":        ("explorer.exe", ["nautilus"],             "file explorer"),
    "text_editor":  ("notepad.exe",  ["gedit"],                "notepad"),
    "paint":        ("mspaint.exe",  ["gimp"],                 "paint"),
    "task_manager": ("taskmgr.exe",  ["gnome-system-monitor"], "task manager"),
    "settings":     ("ms-settings:", ["gnome-control-center"], "settings"),
    "discord":      ("discord:",     ["discord"],              "discord"),
    "spotify":      ("spotify:",     ["spotify"],              "spotify"),
    "whatsapp":     ("whatsapp:",    ["whatsapp-desktop"],     "whatsapp"),
    "telegram":     ("tg:",          ["telegram-desktop"],     "telegram"),
    "vscode":       ("code",         ["code"],                 "visual studio code"),
    "word":         ("winword",      ["libreoffice", "--writer"],  "word"),
    "excel":        ("excel",        ["libreoffice", "--calc"],    "excel"),
    "powerpoint":   ("powerpnt",     ["libreoffice", "--impress"], "powerpoint"),
}
APP_NAMES = list(APPS)
BROWSER_NAMES = ["chrome", "edge", "firefox"]
