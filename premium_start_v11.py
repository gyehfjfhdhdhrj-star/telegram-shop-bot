
ဟုတ်ပါတယ်။ မင်းလိုချင်တဲ့ပုံစံအတိုင်း Reply Keyboard + ပုံမှန် Inline Menu ခွဲတဲ့ version အသစ် လုပ်ပြီးပါပြီ။

အောက်က ၂ ဖိုင်ကို GitHub ထဲ ထည့်ပါ
📥 premium_features_v9.py

📥 premium_start_v9.py

Menu ပုံစံ
Telegram အောက်ဘက် Keyboard နေရာမှာ တစ်ဝက်

🛒 အကောင့်ဝယ်မယ်
👀 အကောင့်ကြည့်မယ်
💰 အကောင့်ရောင်းမယ်
ပုံမှန် message အောက်က Inline Menu နေရာမှာ ကျန်တစ်ဝက်

💸 လျော့စျေးအကောင့်များ
👤 ကျွန်ုပ်၏အကောင့်
✨ အခြား Features
💡 Tips
Admin ဖြစ်ရင် Admin Panel ကိုလည်း Inline Menu ဘက်မှာ ဆက်မြင်ရမယ်။

အရေးကြီးတာ
main.py မပြင်ထားပါဘူး။
supabase_launcher.py မပြင်ထားပါဘူး။

ဖိုင် structure က—

main.py
supabase_launcher.py
premium_features_v9.py
premium_start_v9.py
Render Start Command ကို—

python premium_start_v9.py
ထားပါ။

ပြီးရင် /start နှိပ်ကြည့်ပါ။ အောက်ခြေမှာ Reply Keyboard ပေါ်ပြီး၊ message အောက်မှာ Inline Menu ပေါ်တာကို စစ်ပါ။

ဒီ v9 မှာ source ထဲက start message ကို external interceptor နဲ့ ကိုင်ထားတာကြောင့် မူရင်း /start handler နဲ့ Reply Keyboard မတိုက်အောင်လုပ်ထားပါတယ်။ 


premium_features_v9.py
Code


premium_start_v9.py
Code


Reply Keyboard ကမပေါ်ဘူး သေချာလေး ထည့်ပေးပါ


ဟုတ်ပြီ။ Reply Keyboard မပေါ်တဲ့ အကြောင်းရင်းကို code ထဲက တကယ်စစ်ပြီး တွေ့ပါပြီ။

အရင် v9 မှာ Reply Keyboard installer ကို ကိုယ့် function ကိုယ်ပြန်ခေါ်နေတဲ့ recursive line ရှိသလို၊ install() ထဲကနေလည်း Reply Keyboard layer ကို တကယ် activate မလုပ်ထားတာကြောင့် Keyboard မပေါ်နိုင်တာပါ။ 


ဒီနှစ်ခုကို ပြင်ပြီး v10 လုပ်ထားပါတယ်။

ဖိုင် ၂ ခု
📥 premium_features_v10.py

📥 premium_start_v10.py

Python syntax စစ်ပြီး PASSED ဖြစ်ပါတယ်။

GitHub မှာ
လက်ရှိဖိုင်တွေကို မဖျက်ဘဲ—

main.py
supabase_launcher.py
premium_features_v10.py
premium_start_v10.py
ထားပါ။

Render Start Command ကို—

python premium_start_v10.py
ပြောင်းပါ။

Start နှိပ်ပြီးရင် Reply Keyboard
Telegram chat အောက်ခြေမှာ—

🛒 အကောင့်ဝယ်မယ်    👀 အကောင့်ကြည့်မယ်
💰 အကောင့်ရောင်းမယ်
ပေါ်ရပါမယ်။

ပြီးတော့ Message အောက်က ပုံမှန် Inline Menu မှာ ကျန်တာတွေ ဆက်ရှိပါမယ်။

အခု v10 မှာ main.py မပြင်ထားပါဘူး၊ supabase_launcher.py လည်း မပြင်ထားပါဘူး။

Deploy ပြီး /start နှိပ်တဲ့ screenshot ပို့ပါ။ ဒီတစ်ခါ Keyboard ပေါ်/မပေါ်ကို တိုက်ရိုက်စစ်နိုင်မယ်။ 


premium_features_v10.py
Code


premium_start_v10.py
Code


Today 8:13 PM
start လုပ်လိုက်ပြီဆိုတဲ့ welcomeစာသားတွေမထည့်ပါနဲ့  ကျတော့် အကောင့်ဆိုတာနဲ့ tip နဲ့ ကိုဖြုတ်လိုက်ပါ keyborad menuမှာ လေးခုထည့်ပါ အခြား featuresဆိုတာကိုဖြုတ်ပြီး Inline Menu မှာအကုန်ထည့်ပါ keyborad menu ကဟာတွေကို Inline Menu မှာမပြပါနဲ့ ပင်မ menuဆိုတာကို နိပ်လိုက်ရင် features menuက ဟာကိုဘဲ ပြပါ menuတစ်ခုနိပ်လိုက်တဲ့အရေးမကြီးတဲ့စာတွေကိုမပေါ်လာပါစေနဲ့ နိပ်လိုက်တဲ့ MENU အကြောင်းဘဲ ပေါ်ပါစေ 

အကောင့်ကြည့်မယ်နိပ်လိုက်ရင် အကောင့်နဲ့ စာတွေကို တစ်ခါတွဲ  REPLYပြန်‌အောင်လုပ်ပေးပါ

ဟုတ်ပြီ။ မင်းပြောထားတဲ့ UI ပုံစံအတိုင်း v11 ကို ပြင်ပြီး syntax test အောင်မြင်ပါတယ်။

📥 premium_features_v11.py
📥 premium_start_v11.py

ဒီ version မှာ—

Reply Keyboard ၄ ခု

🛒 အကောင့်ဝယ်မယ်
👀 အကောင့်ကြည့်မယ်
💰 အကောင့်ရောင်းမယ်
💸 လျော့စျေးအကောင့်များ
Inline Menu

❤️ သိမ်းထားတဲ့အကောင့်များ
🆕 အသစ်တင်ထားတဲ့အကောင့်များ
🔎 အဆင့်မြင့်ရှာဖွေမယ်
🛡️ RC လုံးဝစိတ်ချရဆုံးအကောင့်များ
🔥 အထူးစပရှယ် လျော့စျေးအကောင့်များ
Reply Keyboard ထဲက ၄ ခုကို Inline Menu မှာ ထပ်မပြတော့ပါဘူး။

/start မှာ welcome စာသားမပြတော့ဘဲ menu ပဲ ပြမယ်။ 


👤 ကျွန်ုပ်၏အကောင့် နဲ့ 💡 Tips ကို main inline menu ကနေ ဖယ်ထားပါတယ်။

❤️ သိမ်းထားမယ် နဲ့ 🔔 ဈေးကျရင် အသိပေးပါ ကိုနှိပ်ပြီးရင် အတည်ပြုစာ + 🏠 ပင်မ Menu ပဲ ပြမယ်။ 


👀 အကောင့်ကြည့်မယ် မှာ ပထမပုံရဲ့ caption ထဲ Account info အပြည့်အစုံထည့်ပြီး ပုံနဲ့စာကို တစ်ခါတည်းပို့နိုင်အောင် ပြင်ထားပါတယ်။ Telegram media group မရရင် fallback အဖြစ် စာကို သီးသန့်ပို့ပေးမယ်။

GitHub
ဒီ ၂ ဖိုင်ကိုပဲ အသစ်တင်ပါ—

premium_features_v11.py
premium_start_v11.py
Render Start Command:

python premium_start_v11.py
main.py နဲ့ supabase_launcher.py ကို မပြင်ပါနဲ့။


premium_features_v11.py
Code


premium_start_v11.py
Code


Library
/
premium_start_v11.py


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
"""
MLBB MARKET - PREMIUM STARTER v11
--------------------------------
Loads unchanged supabase_launcher.py plus premium_features_v11.py.
Render Start Command:
    python premium_start_v11.py
"""
import importlib.util
import logging
from pathlib import Path
import supabase_launcher

def load_premium():
    path = Path(__file__).with_name("premium_features_v11.py")
    spec = importlib.util.spec_from_file_location("premium_features_v11", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Premium feature module not found: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def main():
    premium = load_premium()
    premium.install(supabase_launcher.original)
    logging.info("PREMIUM_FEATURES_V11_READY")
    supabase_launcher.start_original_bot()

if __name__ == "__main__":
    main()

