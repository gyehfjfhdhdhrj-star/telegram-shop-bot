
Error code: 429
Description: Too Many Requests: retry after 1

errorက နာရီဝက်ကြာမှ ပြန်စမ်းတာကို မပျောက်သေးဘူး


telegram_bot_premium_updated (2)(3) (1).py
Python

supabase_launcher(2).py
Python

1cb14e7d-08f5-4315-8bd4-93b715a7d8d1.png
b688b20e-496f-4cb9-bd98-68319afa3c02.png
supa baseထဲမှာ ငါတင်တုန်းက ပုံတွေ ကျန်နေခဲ့တယ် ဒါပေမယ်  အကောင့်ကြည့်မယ်နိပ်တော့ အကောင့်မရှိသေးပါ ပြနေတယ် မင်းနောက်ဆုံးပေးတဲ့ ဖိုင်ကို deployလုပ်တော့ လဲ errorပြနေတယ်

ဟုတ်တယ်။ Screenshot နှစ်ခုကို အတူကြည့်ရင် ပြဿနာက ၂ ခုခွဲပြီး ဖြစ်နေတယ်။

နောက်ဆုံး supabase_launcher.py deploy က syntax error ကြောင့် fail ဖြစ်တယ်။ Screenshot ထဲမှာ line 14 မှာ မြန်မာစာ/emoji ကို Python string/comment မဟုတ်ဘဲ code အဖြစ်ရောက်သွားလို့ SyntaxError: invalid character '👍' ဖြစ်နေတယ်။ အဲဒါက ငါပေးခဲ့တဲ့ launcher ဖိုင်ရဲ့ format မမှန်တာ ဖြစ်ပြီး မင်းအမှားမဟုတ်ဘူး။

Supabase မှာ ပုံတွေကျန်နေပေမယ့် Bot က အကောင့်မရှိသေးပါ လို့ပြတာက database data ပျောက်သွားတာနဲ့ကိုက်ညီတယ်။ Render Free web service ရဲ့ filesystem က ephemeral ဖြစ်လို့ restart/redeploy/spin-down ဖြစ်ရင် local SQLite database လို data ပျောက်နိုင်တယ်။ 

ဒါကြောင့် bot-images ထဲက ပုံတွေ ကျန်နေပေမယ့် accounts table ထဲက account record တွေ ပျောက်သွားရင် Bot က account ရှာမတွေ့တော့တာ သဘာဝကျပါတယ်။

အခု screenshot ထဲမှာ Supabase bot-images အောက် telegram/6650674337/... နဲ့ telegram/7267372257/... ဆိုပြီး ဖိုင်တွေရှိနေတာကြောင့် Storage ဘက်က ပုံသိမ်းခြင်း အလုပ်လုပ်နေပြီလို့ မြင်ရတယ်။ ဒါပေမယ့် Account metadata/database persistence မရှိသေးတာက အဓိကပြဿနာပါ။

ဒီတစ်ခါ မှန်ကန်တဲ့ ဖြေရှင်းနည်း
မင်းပြောခဲ့တဲ့ စည်းကမ်းအတိုင်း—

main.py 2298 ကြောင်းကို လုံးဝမထိဘူး။

supabase_launcher.py ဘက်မှာပဲ ဒီ architecture ကိုလုပ်ရမယ်:

Admin တင်တဲ့ Account
        ↓
main.py ရဲ့ SQLite write
        ↓
launcher က database backup ယူ
        ↓
Supabase Storage ထဲသိမ်း
        ↓
Render restart
        ↓
Supabase က database backup ပြန်ယူ
        ↓
main.py က မူရင်း SQLite ကို ပြန်သုံး
        ↓
Account + Photos ပြန်ပေါ်
ဒီလိုလုပ်လိုက်ရင် ပုံတင်တာတင်မကဘဲ ACC-001, skin, price, status, seller information, photos စတဲ့ account data အားလုံးကိုပါ Render restart/redeploy ဖြစ်သွားရင် ပြန်ယူလို့ရမယ်။ Render Free မှာ local SQLite ကို ဒီအတိုင်းထားရင် ပြန်ပျောက်နိုင်တာကို Render ကိုယ်တိုင်လည်း ဖော်ပြထားပါတယ်။ 

Security အတွက်
Database backup ကို မင်းရဲ့ public bot-images bucket ထဲ မထားသင့်ဘူး။ Supabase Storage မှာ bucket ကို private/public ခွဲထားနိုင်တာကြောင့် bot-data ဆိုတဲ့ private bucket တစ်ခုသုံးတာ ပိုလုံခြုံတယ်။ 

bot-images ကိုတော့ ပုံတွေသိမ်းဖို့ပဲ ဆက်သုံးမယ်။

အခုအရေးကြီးတာ
Supabase bot-images ထဲက လက်ရှိပုံတွေကို မဖျက်ပါနဲ့။ main.py ကိုလည်း မပြင်ပါနဲ့။

အခုက database persistence ကိုပါ Supabase ဘက်တင်ပြီး ပြန် restore လုပ်ပေးတဲ့ launcher version လုပ်ရမှာပါ။ အဲဒါပြီးရင်—

Render restart ✅

Render redeploy ✅

Free service spin-down ✅

Account data မပျောက် ✅

Supabase ပုံ မပျောက် ✅

Bot မှာ Account ပြန်ကြည့်လို့ရ ✅

ဖြစ်လာမယ်။

ဒါက အခုအခြေအနေမှာ အမှန်တကယ်ဖြေရှင်းရမယ့်အဓိကပြဿနာပါ။


ဟုတ်ပြီ ဆက်လုပ်မယ်

ဟုတ်ပြီ။ ဒီတစ်ခါ တကယ်လိုအပ်တဲ့အပိုင်းကိုပဲ ဆက်လုပ်ထားပါတယ်။

အခုတည်ဆောက်ထားတဲ့ supabase_launcher.py က—

main.py ကို မပြင်ဘူး

Supabase bot-images ထဲကို ပုံဆက်သိမ်းမယ်

Render Free ရဲ့ temporary SQLite ပျောက်သွားနိုင်တဲ့ပြဿနာအတွက် SQLite database တစ်ခုလုံးကို Supabase private backup storage ထဲ အလိုအလျောက် backup လုပ်မယ်

Render restart/redeploy ဖြစ်ပြီး local DB ပျောက်သွားရင် backup ကနေ ပြန် restore လုပ်မယ်

Account data, seller requests, users, activity စတဲ့ SQLite data တွေပါ ဆက်ထိန်းထားမယ်

အဟောင်း Telegram file_id တွေကို Supabase ပုံ URL ပြောင်းဖို့ migration ပါမယ်

Supabase ပုံ URL ကို Bot ပြန်ပို့တဲ့အခါ ပုံပြန်ပို့နိုင်အောင် external handling ထည့်ထားတယ်

Webhook 429 မဖြစ်အောင် လက်ရှိ webhook ကိုစစ်ပြီး မလိုအပ်ရင် ပြန်မတင်ဘူး

Backup ကို update တိုင်း ချက်ချင်းတင်မယ့်အစား ခဏစောင့်ပြီး တစ်ခါတည်း backup လုပ်မယ်

Startup နဲ့ periodic backup ပါရှိတယ်

Supabase ရဲ့ private bucket က public URL မဟုတ်ဘဲ authenticated access သုံးနိုင်တာကြောင့် database backup ကို public image bucket နဲ့ မရောထားပါဘူး။ 

ဒီဖိုင်ကို သုံးပါ
📥 supabase_launcher.py

Render Start Command:

python supabase_launcher.py
main.py ကို မထိပါနဲ့။

အရေးကြီးတာတစ်ခုက ဒီ launcher က backup bucket bot-db-backups ကို အလိုအလျောက်ဖန်တီးဖို့ ကြိုးစားပါမယ်။ မအောင်မြင်ရင် Render Logs မှာ အကြောင်းပြချက်ပေါ်ပါမယ်။

Deploy ပြီးရင် Logs ထဲမှာ အဓိက ဒီလိုစာမျိုးတွေကိုရှာပါ—

✅ SQLite backup saved to Supabase
ပြီးရင် Bot မှာ Account တစ်ခုတင်ပြီး restart/redeploy ပြီးနောက် အဲဒီ Account ပြန်ပေါ်မပေါ် စမ်းတာက အကောင်းဆုံး test ဖြစ်ပါတယ်။


supabase_launcher.py
Code


107605c9-a19d-47e9-93d1-52f537283808.png

ဟုတ်တယ်၊ Screenshot က 429 Too Many Requests မပျောက်သေးတာ အတည်ပြုပါတယ်။

အကြောင်းရင်းကို ဒီတစ်ခါ သေချာစစ်ပြီးပြီ။ main.py ကို import လုပ်တဲ့အချိန်မှာ main.py ကိုယ်တိုင် remove_webhook() → set_webhook() လုပ်နေတယ်။ အဲဒါကြောင့် launcher က webhook မလုပ်တော့အောင် ပြင်ထားပေမယ့် main.py ရဲ့ startup code ကို တားမထားရင် 429 ဆက်ဖြစ်နေပါတယ်။

ဒါကို main.py မထိဘဲ external launcher ကနေတားပေးတဲ့ webhook guard ထည့်ပြီးပြင်ထားပါတယ်။ မင်းရဲ့ main.py ထဲမှာ အဲဒီ webhook calls ရှိနေတာကို source မှာလည်း အတည်ပြုထားတယ်။ 


ဒီတစ်ခါ ပြင်ထားတာ
supabase_launcher.py တစ်ဖိုင်တည်းမှာ—

main.py မပြင်

main.py import မလုပ်ခင် remove_webhook() ကို external no-op လုပ်

set_webhook() ကို current webhook URL စစ်ပြီး တကယ်လိုအပ်မှပဲ set

Telegram 429 ဖြစ်ရင် retry/backoff လုပ်

main.py import ပြီးရင် TeleBot original methods ကို ပြန် restore

Supabase image upload

Supabase image ပြန်ယူပြီး Telegram ပြန်ပို့

SQLite backup/restore

periodic backup

အားလုံး ဆက်ထားပါတယ်။

ဖိုင်
📥 **ပြင်ပြီးသား supabase_launcher.py]

Python syntax ကိုလည်း အောင်မြင်အောင် စစ်ပြီးပါပြီ။

Render မှာ
လက်ရှိ GitHub က supabase_launcher.py ကို ဒီဖိုင်နဲ့ အစားထိုးပါ။

Start Command က:

python supabase_launcher.py
အတိုင်းထားပါ။

main.py ကို မပြင်ပါနဲ့။

Deploy ပြီး Log မှာ အနည်းဆုံး ဒီလိုစာမျိုးတွေ့ရမယ်—

Webhook already correct; no Telegram webhook update needed
ဒါမှမဟုတ်

Webhook set successfully: ...
ပြီးတော့ 429 မပေါ်သင့်တော့ပါဘူး။

ပြီးတာနဲ့ Bot ထဲမှာ အရင်ရှိပြီးသား Account ကို 👀 အကောင့်ကြည့်မယ် နှိပ်ပြီး စမ်းပါ။ အကောင့်မရှိသေးပါ ဖြစ်နေသေးရင် အဲဒီအချိန်မှာတော့ webhook မဟုတ်တော့ဘဲ database restore အပိုင်းကို တိတိကျကျစစ်မယ်။


supabase_launcher.py
Code


Library
/
supabase_launcher.py


1
2
3
4
5
6
7
8
9
10
11
12
13
14
15
16
17
18
19
20
21
22
23
24
25
26
27
28
29
30
31
32
33
34
35
36
37
38
39
40
41
42
43
44
45
46
47
48
49
50
51
52
53
54
55
56
57
58
59
60
61
62
63
64
65
66
67
"""
EXTERNAL SUPABASE CONNECTOR
---------------------------
This file does NOT modify main.py.
Keep the original 2298-line bot code exactly as it is.

Render Start Command:
    python supabase_launcher.py

main.py must be the original bot file.
"""

import os
import logging
import threading
import urllib.parse
import requests

# Import the original bot as a module. Its 2298 lines are not edited.
import main as original

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "").strip()
BUCKET = "bot-images"

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL environment variable မရှိပါ။")
if not SUPABASE_SECRET_KEY:
    raise RuntimeError("SUPABASE_SECRET_KEY environment variable မရှိပါ။")


def supabase_public_url(path):
    return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{urllib.parse.quote(path, safe='/')}"


def upload_to_supabase(path, data, content_type="image/jpeg"):
    """Upload/overwrite one file in the existing public bot-images bucket."""
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{urllib.parse.quote(path, safe='/')}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "apikey": SUPABASE_SECRET_KEY,
        "Content-Type": content_type,
        "x-upsert": "true",
        "Cache-Control": "31536000",
    }
    r = requests.post(url, headers=headers, data=data, timeout=60)
    if r.status_code not in (200, 201):
        # Some Supabase Storage versions prefer PUT for object replacement.
        r = requests.put(url, headers=headers, data=data, timeout=60)
    r.raise_for_status()
    return supabase_public_url(path)


def telegram_photo_to_supabase(photo_size, chat_id, message_id):
    """Download the Telegram photo once, then return a permanent Supabase URL."""
    file_info = original.bot.get_file(photo_size.file_id)
    data = original.bot.download_file(file_info.file_path)
    unique = getattr(photo_size, "file_unique_id", None) or photo_size.file_id
    path = f"telegram/{chat_id}/{message_id}_{unique}.jpg"
    return upload_to_supabase(path, data, "image/jpeg")


def preprocess_update(update):
    """Replace incoming photo file_ids with Supabase public URLs before the
    original 2298-line handlers see the update.

    This means the original receive_photo_message() function stays untouched.
