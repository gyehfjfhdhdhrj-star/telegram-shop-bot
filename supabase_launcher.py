
Error code: 429
Description: Too Many Requests: retry after 1

errorက နာရီဝက်ကြာမှ ပြန်စမ်းတာကို မပျောက်သေးဘူး


telegram_bot_premium_updated (2)(3) (1).py
Python

supabase_launcher(2).py
Python

ကောင်းပြီ 👍 အခုကစပြီး Simple + Premium + မြန် + မရှုပ်တဲ့ Bot UX ကို အခြေခံထားပြီး ဆက်သွားမယ်။

အရေးကြီးဆုံးစည်းကမ်းကတော့ ရှိပြီးသား အလုပ်လုပ်နေတဲ့ flow တွေကို မဖျက်ဘဲ၊ မလိုအပ်တဲ့နေရာကို မထိဘဲ တိုးတက်အောင်ပဲလုပ်မယ် ဆိုတာပဲ။


ဟုတ်တယ် စလုပ်ပါ

ဟုတ်ပြီ။ ဒီတစ်ခါ မင်းရဲ့ မူရင်း main.py ကို လုံးဝမပြင်ဘဲ supabase_launcher.py တစ်ဖိုင်တည်းကို ပြန်တည်ဆောက်ထားပါတယ်။ မူရင်းဖိုင်မှာ 2298 ကြောင်း ရှိတာကို စစ်ထားပါတယ်။ 


အခု launcher အသစ်က အရင်ပြဿနာကို ၂ ဖက်လုံးက ဖြေရှင်းထားပါတယ်—

ပုံသိမ်းတဲ့အပိုင်း
Telegram ကလာတဲ့ပုံကို bot-images ထဲ Supabase အမြဲသိမ်းမယ်။ 


ပုံပြန်ပြတဲ့အပိုင်း
Bot က Account ကြည့်တဲ့အချိန် Supabase URL ကို Telegram ဆီတိုက်ရိုက်ပေးမယ့်အစား Supabase ကနေ server-side download ပြန်ယူပြီး Telegram ကို photo အဖြစ် upload ပြန်လုပ်ပေးမယ်။ ဒါကြောင့် Supabase ထဲမှာ ပုံရှိနေသရွေ့ အချိန်ကြာသွားလည်း Bot က ပြန်ပြနိုင်ပါတယ်။

Webhook 429 အတွက်လည်း launcher က remove_webhook() / set_webhook() ကို ထပ်မလုပ်တော့ပါဘူး။ မူရင်း main.py ရဲ့ webhook setup ကိုပဲ အသုံးပြုပါတယ်။

ဖိုင်အသစ်
📥 supabase_launcher_v2.py

Render မှာ
GitHub ရဲ့ လက်ရှိ

supabase_launcher.py
ကို ဒီဖိုင်နဲ့ အစားထိုးပြီး filename ကို supabase_launcher.py အတိုင်းထားပါ။

Start Command က—

python supabase_launcher.py
အတိုင်းထားပါ။

main.py ကို မထိပါနဲ့။ မူရင်း 2298 ကြောင်းအတိုင်းထားပါ။ 


Deploy ပြီးရင် စမ်းသပ်ပုံက—

Admin → အကောင့်တင်မယ် → ပုံတင် → ပုံအကုန်တင်ပြီးပြီ → ဈေးထည့်

ပြီးရင်

Bot → အကောင့်ကြည့်မယ် → အဲဒီ Account ကိုပြန်ကြည့်

လုပ်ပါ။

Render Logs မှာ

SUPABASE_UPLOAD_OK
နဲ့ account ပြန်ကြည့်တဲ့အချိန်

SUPABASE_DOWNLOAD_OK
ပေါ်လာရပါမယ်။

အခု main.py ကိုတော့ မပြင်ထားပါဘူး။


supabase_launcher_v2.py
Code


အခုမင်းက ဘာကိုပြင်ပေးထားတာလဲ

အခုနောက်ဆုံး ငါလုပ်ပေးထားတာက Bot ရဲ့ မူရင်း main.py flow တွေကို ပြောင်းတာမဟုတ်ဘဲ supabase_launcher.py ကိုပဲ update လုပ်ထားတာပါ။

အဓိကပြင်ထားတာ ၃ ခုရှိတယ်—

1. ပုံသိမ်းတာ
Admin/Seller က Telegram မှာ ပုံပို့လိုက်တာနဲ့ launcher က Telegram ကနေ ပုံကို download ယူပြီး Supabase bot-images bucket ထဲ upload လုပ်ပေးတယ်။ လက်ရှိ launcher မှာ ဒီ upload logic ရှိပြီးသားပါ။ 


2. ပုံပြန်ကြည့်တာ
အရင်က အဓိကပြဿနာက Supabase ထဲမှာ URL ရှိနေပေမယ့် Bot ရဲ့ account display function က Telegram InputMediaPhoto နဲ့ အဲဒီ reference ကို တိုက်ရိုက်ပြန်သုံးနေတာပါ။ မူရင်း main.py မှာ account ပုံတွေကို acc["photos"] ထဲကနေယူပြီး Telegram ကို ပြန်ပို့တာကို တွေ့ရတယ်။ 


အဲဒါကြောင့် launcher အသစ်မှာ Supabase ကနေ ပုံကို server-side ပြန်ယူပြီး Telegram ကို photo အဖြစ် ပြန်ပို့တဲ့ layer ထည့်ထားတာပါ။ ရည်ရွယ်ချက်က Supabase ထဲမှာ ပုံရှိနေသရွေ့ Bot မှာ account ပြန်ကြည့်တဲ့အခါ ပုံပြန်ပေါ်လာအောင်ပါ။

3. Webhook 429
အရင် supabase_launcher.py က startup တိုင်း remove_webhook() နဲ့ set_webhook() ပြန်လုပ်နေတာကြောင့် 429 Too Many Requests ဖြစ်ခဲ့တယ်။ 


နောက် version မှာတော့ launcher က webhook ကို ထပ်မပြောင်းတော့ဘဲ မူရင်း main.py ရဲ့ webhook setup ကိုပဲ အသုံးပြုဖို့လုပ်ထားတယ်။

မပြင်ထားတာ
main.py 2298 ကြောင်းကို မပြင်ထားပါဘူး။ မူရင်းက photos ကို database ထဲသိမ်းတဲ့ structure နဲ့ account display flow တွေက မူရင်းအတိုင်းပါ။ 


တစ်ချက်တော့ အရေးကြီးတယ် — ဒီ version က “ဘာပုံမဆို အမြဲပြန်ရမယ်” လို့ ငါအခုချက်ချင်းအာမမခံနိုင်သေးဘူး။ အကြောင်းက မင်းရဲ့ main.py က account photos field ထဲမှာ ဘယ်အချိန်မှာ Telegram file ID၊ ဘယ်အချိန်မှာ Supabase URL ဝင်နေတယ်ဆိုတာကို ငါတို့ live environment ထဲမှာ မစမ်းရသေးလို့ပါ။

အခု အကောင်းဆုံးက အသစ်တင်ထားတဲ့ account တစ်ခုကို ၁ ပုံတင်ပြီး Browse Account နဲ့ ပြန်ကြည့်တာပါ။ အဲဒီ test နဲ့ launcher အသစ်ရဲ့ save/retrieve နှစ်ဖက်လုံး တကယ်အလုပ်လုပ်မလုပ် ချက်ချင်းသိနိုင်ပါတယ်။


Library
/
supabase_launcher_v2.py


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
68
69
70
71
72
73
"""
EXTERNAL SUPABASE PHOTO CONNECTOR — V2
--------------------------------------
The original main.py is NOT modified.
Keep the original 2298-line bot file exactly as it is.

Render Start Command:
    python supabase_launcher.py

Required environment variables:
    TELEGRAM_TOKEN
    ADMIN_ID
    PUBLIC_URL
    SUPABASE_URL
    SUPABASE_SECRET_KEY

Supabase bucket:
    bot-images (public)
"""

import io
import os
import logging
import threading
import urllib.parse
from typing import Any

import requests
import telebot
from telebot.types import InputMediaPhoto, InputFile

# Import original bot. Do not edit its source.
import main as original

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "").strip()
BUCKET = os.getenv("SUPABASE_BUCKET", "bot-images").strip() or "bot-images"

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL environment variable မရှိပါ။")
if not SUPABASE_SECRET_KEY:
    raise RuntimeError("SUPABASE_SECRET_KEY environment variable မရှိပါ။")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

def supabase_public_url(path: str) -> str:
    return (
        f"{SUPABASE_URL}/storage/v1/object/public/"
        f"{urllib.parse.quote(BUCKET, safe='')}/{urllib.parse.quote(path, safe='/')}"
    )


def _storage_object_url(path: str) -> str:
    return (
        f"{SUPABASE_URL}/storage/v1/object/"
        f"{urllib.parse.quote(BUCKET, safe='')}/{urllib.parse.quote(path, safe='/')}"
    )


def upload_to_supabase(path: str, data: bytes, content_type: str = "image/jpeg") -> str:
    url = _storage_object_url(path)
    headers = {
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "apikey": SUPABASE_SECRET_KEY,
        "Content-Type": content_type,
