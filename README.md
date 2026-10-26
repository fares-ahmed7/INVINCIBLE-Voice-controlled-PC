# INVINCIBLE – Voice-controlled PC

تحكّم في الكمبيوتر بصوتك (عربي، إنجليزي، أو الاتنين مع بعض).
بيسمع كلامك، بيفهمه بموديل AI شغال على جهازك، وبينفّذ الأمر **من قائمة أوامر آمنة بس**.

```
🎤 "افتح ايدج وابحث عن الطقس"
   │
   ▼  Speech-to-Text (Google, عربي + إنجليزي مع بعض)
   ▼  understand_command()  ← Ollama محلي (qwen3:4b)
   ▼  {"action": "web_search", "query": "الطقس", "browser": "edge"}
   ▼  execute()             ← Executor (whitelist)
   ▼  ✅ بيفتح Edge على بحث جوجل
```

شغّال على **Windows** بس.

---

## التشغيل السريع

```powershell
# 1) ثبّت Ollama:  https://ollama.com/download

# 2) نزّل الموديل (حوالي 2.5GB، مرة واحدة)
ollama pull qwen3:4b

# 3) بيئة بايثون
python -m venv venv
.\venv\Scripts\Activate.ps1      # Windows PowerShell
# venv\Scripts\activate.bat      # Windows cmd
pip install -r requirements.txt

# 4) شغّل
python main.py --voice           # بالصوت (عربي + إنجليزي مع بعض)
python main.py                   # بالكتابة
python main.py --voice --debug  # بالصوت + سجل أوقات (STT / AI / تنفيذ) عشان نعرف مين بطي
python main.py --voice --no-wake        # من غير wake word
python main.py --max-per-minute 20      # حد الأوامر في الدقيقة (الافتراضي 10، و0 = بلا حد)
```

اخرج بقول **exit** أو **خروج** (أو `Ctrl+C`).

> لو PowerShell قالك "running scripts is disabled":
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

---

## تقدر تقول إيه

| الأمر | أمثلة |
|---|---|
| فتح تطبيق | "افتح ديسكورد"، "open chrome"، "افتح الآلة الحاسبة" |
| بحث | "افتح جوجل وابحث عن أخبار الطقس"، "search google for python" |
| بحث في متصفح معين | "افتح ايدج وابحث عن X"، "open chrome and search for cats" |
| بحث في يوتيوب | "دور على أغاني عمرو دياب في يوتيوب" |
| فتح موقع | "افتح يوتيوب"، "open github" |
| فولدر جديد | "اعمل فولدر اسمه Projects" (بيتعمل على Desktop) |
| فتح فولدر | "افتح فولدر Downloads" |
| الصوت | "ارفع الصوت"، "وطّي الصوت"، "اكتم الصوت"، "شغل الصوت" (unmute)، "خلي الصوت 50" (نسبة دقيقة بالـ pycaw) |
| إيقاف الجهاز | "اقفل الجهاز" (بيسألك "Are you sure?"، ومفيش رد في 5 ثواني = إلغاء) |

أي حاجة برّه القائمة دي بتطلع `Didn't understand` ومبتتنفذش.

**التطبيقات:** أول ما البرنامج يشتغل بيعمل Scan لقايمة Start (بتاعتك و All Users) ويلاقي التطبيقات المتثبتة تلقائيًا.
وفي كمان قايمة Manual Override في `ai/apps.py` فيها اختصارات وأسماء عربية:
chrome, firefox, edge, calculator, terminal, files, text_editor, paint, task_manager,
settings, discord, spotify, whatsapp, telegram, vscode, word, excel, powerpoint.

**المواقع المتاحة:** google, youtube, facebook, gmail, github, whatsapp, wikipedia.

---

## الصوت: عربي وإنجليزي مع بعض

Google بيفهم لغة واحدة بس في الطلب الواحد، فالوضع الافتراضي (`--lang mixed`) بيبعت **نفس الصوت مرتين**
(عربي + إنجليزي) في نفس الوقت، وبيدّي الموديل النسختين:

```
📝 [ar] اوبن اي جي اند سيرش ويذر || [en] open edge and search weather
🤖 {"action": "web_search", "query": "weather", "browser": "edge", ...}
```

```powershell
python main.py --voice                    # مخلوط (الافتراضي)
python main.py --voice --lang ar-EG       # عربي بس
python main.py --voice --lang en-US       # إنجليزي بس
python voice_demo.py --list-mics          # اعرض الميكروفونات
python main.py --voice --mic 1            # اختار ميكروفون
```

- محتاج **نت** (الـ STT بتاع Google).
- محتاج **PyAudio** للميكروفون: `pip install pyaudio`.

### Wake word

في وضع الصوت لازم تبدأ الأمر بكلمة **invincible** أو **إنفينسيبل** (وبيتقبل اختلافات الـ STT زي "invisible"):

```
🎤 "invincible افتح كروم"
📝 افتح كروم
```

- بتتشال قبل ما تتبعت للموديل.
- عطّلها بـ `--no-wake` أو `INVINCIBLE_WAKE=0`.
- كلمة الخروج (`exit`/`خروج`) شغالة من غير wake word.

### التأكيد بالصوت

الأوامر الخطرة (زي الإيقاف) بتسألك **"Are you sure?"** وبتستنى رد **yes/no** أو **نعم/لا** حوالي 5 ثواني.
مفيش رد = إلغاء. في وضع الكتابة نفس السؤال بيتكتب في الـ terminal.

---

## الأمان

الموديل **مبينفّذش حاجة**، هو بس بيحوّل الكلام لـ JSON. كل حاجة بتتنفّذ جاية من كودنا:

- **Whitelist:** التطبيقات والمواقع والأوامر معروفة مسبقًا (Manual + Start Menu Scan). أي حاجة برّه القايمة بتتقفل.
- **اسم التطبيق بس:** الموديل بيدّي اسم تطبيق قصير — لو حاول يرجّع Path أو Command أو URL بيتم رفضه. الإطلاق بيحصل على Target من عندنا بس (`os.startfile` على اختصار Start أو Target مسجّل).
- **الموديل مبيدّيش رابط أبدًا:** بيدّي كلمة البحث أو اسم موقع بس. الدومين (`google.com`/`youtube.com`) ثابت في الكود، والكلمة بتتحوّل لصيغة آمنة (`quote_plus`).
- **من غير `shell=True`:** الأوامر بتتشغّل كقوائم.
- **أسماء الفولدرات** بتتنضّف (حروف وأرقام ومسافة و `-` `_` بس).
- **الإيقاف** وأي أمر خطر بيطلب تأكيد. في وضع الصوت بتجاوب yes/no خلال 5 ثواني، ومفيش رد = إلغاء.
- التطبيقات بتتفتح **منفصلة عن الـ terminal**، فمخرجاتها مبتظهرش عندك ولو قفلت البرنامج بتفضل شغالة.

---

## السجلات

كل أمر بيتنفّذ بيتسجل في `logs/invincible.log`: الوقت، النص الخام، JSON اللي رجع من الموديل، والنتيجة.
الملف بيلفّ تلقائيًا عند 1MB (3 نسخ احتياطية)، ومجلد `logs/` مش بيتعمل Commit.

---

## الهيكل

```
ai/
  schema.py          # شكل الـ JSON (العقد بين الموديولات) ← اقراه الأول
  apps.py            # Manual Override: أسماء/اختصارات عربية + Targets خاصة
  app_registry.py    # Start Menu Scan + التحقق من اسم التطبيق ومطابقته
  command_parser.py  # understand_command() + الـ prompt + التحقق من ردّ الموديل
executor.py          # بينفّذ الأمر فعلًا (Windows)
main.py              # الصوت/الكتابة → AI → التنفيذ  (ده اللي بتشغّله)
voice_demo.py        # الميكروفون + STT وطباعة النص/الـ JSON بس
tests/
  test_cases.json    # جمل الاختبار (عربي/إنجليزي/مخلوط)
  evaluate.py        # بيقيس الدقة والسرعة
```

---

## إضافة حاجات جديدة

**تطبيق جديد**: مش محتاج تسجّله — البرنامج بيلاقي تطبيقات قايمة Start تلقائيًا.

لو عايز **Override يدوي** (اسم عربي، اختصار، أو Launcher خاص زي Discord)، زوّد سطر في `ai/apps.py`:
```python
#            Windows target   Start-Menu keyword
"notepadpp": ("notepad++.exe", "notepad++"),
```
الـ target بيكون اسم exe مسجّل في Windows، أو رابط زي `discord:`.
ولو عايز اسم عربي أو Alias، زوّده في `ALIASES` في نفس الملف:
```python
"نوتباد": "notepad++",
```
لو الـ target فشل، الكود بيدوّر على اختصار بالكلمة دي في قايمة Start.
Manual Override دايمًا بيكسب قبل الـ Scan.

**موقع جديد**: ضيف الاسم في `SiteName` (`ai/schema.py`) + سطر `open_website` في `SYSTEM_PROMPT` + قاموس `SITES` في `executor.py`.

**أمر جديد (action)**:
1. `ai/schema.py` ← ضيفه في `ActionName` (وأي حقل جديد)
2. `ai/command_parser.py` ← مثال في `SYSTEM_PROMPT` + تحقق من الحقول
3. `executor.py` ← الـ mapping في `execute()`
4. `tests/test_cases.json` ← جمل اختبار
5. `python -m tests.evaluate` ← تأكد إن الدقة ما قلّتش

---

## استخدامه من كود تاني

```python
from ai import understand_command
from executor import execute

cmd = understand_command("افتح كروم")
# {"action": "open_app", "app": "chrome", ...}
print(execute(cmd))   # "✅ Opening chrome"
```

- `understand_command` **ما بترميش exception** لو الموديل رجّع حاجة غلط، بترجّع `{"action": "unknown"}`.
- لو Ollama مش شغال بترمي Exception (اتعامل معاه في الـ UI).
- غيّر الموديل: `INVINCIBLE_MODEL=qwen3:1.7b` (أخف) أو `qwen3:8b` (أدق في الجمل المخلوطة).
- Ollama على جهاز تاني: `OLLAMA_HOST=http://IP:11434`.
- في PowerShell: `$env:INVINCIBLE_MODEL="qwen3:8b"`.

---

## مشاكل شائعة

| المشكلة | الحل |
|---|---|
| `App not found: X` | التطبيق مش متثبت أو اسمه مختلف. جرّب تفتحه من `Win + R` بنفس الاسم، أو ضيف Alias في `ai/apps.py` |
| الصوت مش بيسمع | `--list-mics` وبعدين `--mic <رقم>`، وتأكد من Privacy → Microphone في Windows |
| `Speech service error` | مفيش نت |
| الموديل بيفهم غلط | ضيف الجملة في `test_cases.json` ومثال في `SYSTEM_PROMPT`، أو جرّب موديل أكبر |
| خطأ اتصال بـ Ollama | شغّله: `ollama serve` |
| أول أمر بطيء | عادي، الموديل بيتحمّل في الرام أول مرة |

---

## حالة المشروع

- ✅ الفهم (AI)، الصوت المخلوط، وكل الأوامر في الجدول فوق.
- 💡 مقترحات: أمر "اقفل التطبيق".

## Git

- ما ترفعوش الموديل نفسه (Ollama بيخزّنه برّه الريبو).
- أي جملة الموديل غلط فيها ← ضيفوها في `test_cases.json` في commit لوحده.
