import os
import telebot
from flask import Flask, request
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

TELEGRAM_TOKEN = '8614749096:AAE6EY0g2593hpXHmxrOWnhP3d1SgTuDSr4'
ADMIN_ID = 7267372257  

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# အကောင့်ဒေတာဘေ့စ်နှင့် အချက်အလက်များ ရေရှည်သိမ်းဆည်းရန်
accounts_db = {}
user_data = {}    
acc_counter = 1

# Menu များနှင့် လိုက်ဖက်သော ပုံစစ်စစ်များ (Banners)
BANNER_WELCOME = "https://images.unsplash.com/photo-1542751371-adc38448a05e?w=800"
BANNER_BUY = "https://images.unsplash.com/photo-1511512578047-dfb367046420?w=800"
BANNER_BROWSE = "https://images.unsplash.com/photo-1550745165-9bc0b252726f?w=800"
BANNER_SELL = "https://images.unsplash.com/photo-1563986768609-322da13575f3?w=800"
BANNER_TIPS = "https://images.unsplash.com/photo-1516321318423-f06f85e504b3?w=800"

@app.route('/')
def home():
    return "Bot is running 24/7 successfully! 🚀"

@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_str = request.get_data().decode('UTF-8')
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return '', 200
    return 'OK', 200

# 1. MAIN MENU & ADMIN CHECK
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    user_data[user_id] = {} 
    
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🛒 အကောင့်ဝယ်မည် 💎", callback_data="buy_acc"),
        InlineKeyboardButton("👀 အကောင့်တွေကြည့်မယ် 🚀", callback_data="browse_acc_0"),
        InlineKeyboardButton("💰 အကောင့်ရောင်းမည် 🔥", callback_data="sell_acc"),
        InlineKeyboardButton("💡 အသုံးဝင်တဲ့ Tips များ 📌", callback_data="show_tips")
    )
    
    if user_id == ADMIN_ID:
        markup.add(
            InlineKeyboardButton("👑 [ADMIN] အကောင့်အသစ်တင်ရန် ➕", callback_data="admin_add_acc"),
            InlineKeyboardButton("📊 [ADMIN] လက်ကျန်အကောင့်များကြည့်ရန် 📂", callback_data="admin_view_acc")
        )
        bot.send_photo(message.chat.id, BANNER_WELCOME, caption="👑 မင်္ဂလာပါ Admin ⚡️ သင့်အတွက် စီမံခန့်ခွဲမှု Menu များ အဆင်သင့် ဖြစ်ပါပြီခင်ဗျာ။", reply_markup=markup)
    else:
        bot.send_photo(message.chat.id, BANNER_WELCOME, caption="👋 မင်္ဂလာပါ 🎮 Gaming Shop Bot မှ ကြိုဆိုပါတယ် ⚡️\n\nအောက်ပါ Menu မှ လိုအပ်သည်များကို ရွေးချယ်နိုင်ပါပြီ ခင်ဗျာ 📲", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "back_home")
def go_home(call):
    user_id = call.message.chat.id
    user_data[user_id] = {}
    
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🛒 အကောင့်ဝယ်မည် 💎", callback_data="buy_acc"),
        InlineKeyboardButton("👀 အကောင့်တွေကြည့်မယ် 🚀", callback_data="browse_acc_0"),
        InlineKeyboardButton("💰 အကောင့်ရောင်းမည် 🔥", callback_data="sell_acc"),
        InlineKeyboardButton("💡 အသုံးဝင်တဲ့ Tips များ 📌", callback_data="show_tips")
    )
    if user_id == ADMIN_ID:
        markup.add(
            InlineKeyboardButton("👑 [ADMIN] အကောင့်အသစ်တင်ရန် ➕", callback_data="admin_add_acc"),
            InlineKeyboardButton("📊 [ADMIN] လက်ကျန်အကောင့်များကြည့်ရန် 📂", callback_data="admin_view_acc")
        )
    bot.send_photo(user_id, BANNER_WELCOME, caption="🏠 ပင်မ Menu သို့ ပြန်ရောက်ပါပြီ ⚡️", reply_markup=markup)

# 2. BUY FLOW (Menu ပါဝင်ပြီး Skin နှင့် Budget ကို စာရိုက်ရှာနိုင်ခြင်း)
@bot.callback_query_handler(func=lambda call: call.data == "buy_acc")
def buy_step1(call):
    user_id = call.message.chat.id
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔙 ပင်မ Menu သို့ပြန်သွားမည် 🏠", callback_data="back_home"))
    
    msg = bot.send_photo(user_id, BANNER_BUY, caption="✨ ကျေးဇူးပြု၍ ရှာလိုသော **Skin နာမည်** (ဥပမာ - Collector, Gusion, Alucard စသည်ဖြင့်) ကို တိုက်ရိုက် စာရိုက် ပို့ပေးပါ ✍️", reply_markup=markup)
    bot.register_next_step_handler(msg, process_skin_text_input)

def process_skin_text_input(message):
    user_id = message.chat.id
    if message.text and message.text.startswith('/'):
        return
    skin_keyword = message.text.lower().strip() if message.text else ""
    user_data[user_id] = {'skin_keyword': skin_keyword}
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔙 ပင်မ Menu သို့ပြန်သွားမည် 🏠", callback_data="back_home"))
    
    msg = bot.send_message(user_id, "💰 ကျေးဇူးပြု၍ သုံးစွဲလိုသော **ငွေပမာဏ (Budget)** ကို ဂဏန်းဖြင့် တိုက်ရိုက် ရိုက်ထည့်ပေးပါ ✍️\n(ဥပမာ - 50000 သို့မဟုတ် 150000)", reply_markup=markup)
    bot.register_next_step_handler(msg, process_budget_text_input)

def process_budget_text_input(message):
    user_id = message.chat.id
    if message.text and message.text.startswith('/'):
        return
    try:
        max_price = int(message.text.replace(",", "").strip())
    except ValueError:
        bot.send_message(user_id, "⚠️ ကျေးဇူးပြု၍ မှန်ကန်သော ငွေပမာဏ ဂဏန်းကိုသာ ရိုက်ထည့်ပေးပါ ❌ /start ဖြင့် ပြန်စပါ။")
        return
        
    skin_keyword = user_data.get(user_id, {}).get('skin_keyword', '')
    
    matched = []
    for acc_id, acc in accounts_db.items():
        if acc['price'] <= max_price:
            if not skin_keyword or skin_keyword in acc['title'].lower() or skin_keyword in acc['skins'].lower():
                matched.append((acc_id, acc))
                
    if not matched:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 ပင်မ Menu သို့ပြန်သွားမည် 🏠", callback_data="back_home"))
        bot.send_message(user_id, "❌ စိတ်မကောင်းပါ၊ သင့်တောင်းဆိုချက်နှင့် ကိုက်ညီသော အကောင့် မရှိသေးပါ ခင်ဗျာ 😔", reply_markup=markup)
        return
        
    bot.send_message(user_id, f"🎯 သင့်တောင်းဆိုချက်နှင့် ကိုက်ညီသော အကောင့် ({len(matched)}) ခု တွေ့ရှိပါသည် ⚡️")
    for acc_id, acc in matched:
        text = f"🆔 {acc_id} - {acc['title']}\n✨ Skins: {acc['skins']}\n💵 ဈေးနှုန်း: {acc['price']:,} MMK"
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("🔍 အသေးစိတ် ကြည့်မည် 📸", callback_data=f"detail_{acc_id}"),
            InlineKeyboardButton("🛒 အကောင့်ဝယ်မည် 💎", callback_data=f"confirm_buy_{acc_id}")
        )
        if acc['photos']:
            bot.send_photo(user_id, acc['photos'][0], caption=text, reply_markup=markup)
        else:
            bot.send_message(user_id, text, reply_markup=markup)

# 3. BROWSE ACCOUNTS (Banner ပါရှိပြီး ပုံစစ်စစ် ၅ ပုံသာပြသမည်)
@bot.callback_query_handler(func=lambda call: call.data.startswith("browse_acc_"))
def browse_accounts(call):
    idx = int(call.data.split("_")[2])
    acc_keys = list(accounts_db.keys())
    
    if not acc_keys:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 ပင်မ Menu သို့ပြန်သွားမည် 🏠", callback_data="back_home"))
        bot.send_photo(call.message.chat.id, BANNER_BROWSE, caption="❌ လောလောဆယ် ပြသရန် အကောင့် မရှိသေးပါ ခင်ဗျာ 😔", reply_markup=markup)
        return
        
    if idx >= len(acc_keys):
        idx = 0
        
    acc_id = acc_keys[idx]
    acc = accounts_db[acc_id]
    
    # ဓာတ်ပုံစစ်စစ် ၅ ပုံကိုသာ တိုက်ရိုက်ပြသခြင်း
    photos = acc['photos'][:5]
    if photos:
        media = [telebot.types.InputMediaPhoto(p) for p in photos]
        bot.send_media_group(call.message.chat.id, media)
        
    text = f"📌 အကောင့် ID: {acc_id}\n📝 {acc['title']}\n✨ Skins: {acc['skins']}\n💵 ဈေးနှုန်း: {acc['price']:,} MMK"
    
    next_idx = idx + 1 if (idx + 1) < len(acc_keys) else 0
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("➡️ နောက်အကောင့်ဆက်ကြည့်မည် 🚀", callback_data=f"browse_acc_{next_idx}"),
        InlineKeyboardButton("🛒 အကောင့်ဝယ်မည် 💎", callback_data=f"confirm_buy_{acc_id}"),
        InlineKeyboardButton("🔙 ပင်မ Menu သို့ပြန်သွားမည် 🏠", callback_data="back_home")
    )
    bot.send_photo(call.message.chat.id, BANNER_BROWSE, caption=text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("detail_"))
def view_detail(call):
    acc_id = call.data.replace("detail_", "")
    acc = accounts_db.get(acc_id)
    if acc and acc['photos']:
        bot.send_message(call.message.chat.id, f"🔍 {acc_id} ၏ အကောင့်ပုံစစ်စစ်များ ({len(acc['photos'])} ပုံ) 📸")
        media = [telebot.types.InputMediaPhoto(p) for p in acc['photos'][:10]]
        bot.send_media_group(call.message.chat.id, media)

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_buy_"))
def confirm_buy(call):
    acc_id = call.data.replace("confirm_buy_", "")
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("👨‍💻 Admin ထံ တိုက်ရိုက်ဆက်သွယ်မည် 🚀", url="https://t.me/your_admin_username"))
    bot.send_message(call.message.chat.id, f"✅ {acc_id} အကောင့်ကို ဝယ်ယူရန် Admin ထံ တိုက်ရိုက် ဆက်သွယ်နိုင်ပါပြီ ခင်ဗျာ 💎", reply_markup=markup)

# 4. SELL FLOW (အကောင့်ရောင်းမည် - ဈေးနှုန်း တိုက်ရိုက်ရိုက်ထည့်ရန်)
@bot.callback_query_handler(func=lambda call: call.data == "sell_acc")
def sell_step1(call):
    user_id = call.message.chat.id
    user_data[user_id] = {'photos': []}
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ ဓာတ်ပုံများ အကုန်ပို့ပြီးပြီ 🚀", callback_data="sell_photos_done"))
    
    bot.send_photo(user_id, BANNER_SELL, caption="📸 အဆင့် (၁/၂) ⚡️\n\nသင့်အကောင့်၏ Skin ဓာတ်ပုံများကို ဆက်တိုက် ပို့ပေးပါ 📲\n\nပုံများ အကုန်ပို့ပြီးပါက အောက်ပါ Button ကို နှိပ်ပါ 👇", reply_markup=markup)

@bot.message_handler(content_types=['photo'])
def collect_sell_photos_handler(message):
    user_id = message.from_user.id
    if user_id in user_data and 'photos' in user_data[user_id] and 'error_info' not in user_data[user_id]:
        user_data[user_id]['photos'].append(message.photo[-1].file_id)

@bot.callback_query_handler(func=lambda call: call.data == "sell_photos_done")
def sell_photos_complete(call):
    user_id = call.message.chat.id
    if not user_data.get(user_id, {}).get('photos'):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ ဓာတ်ပုံများ အကုန်ပို့ပြီးပြီ 🚀", callback_data="sell_photos_done"))
        bot.send_message(user_id, "⚠️ ဓာတ်ပုံ မပို့ရသေးပါ❌ ဓာတ်ပုံများ အရင် ပို့ပေးပါ 📸", reply_markup=markup)
        return
        
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("✅ Error / Issue လုံးဝမရှိ 🟢", callback_data="err_none"),
        InlineKeyboardButton("⚠️ Error နည်းနည်းပါသည် 🟡", callback_data="err_minor"),
        InlineKeyboardButton("🚫 Ban / Issue ထိဖူးသည် 🔴", callback_data="err_major")
    )
    bot.send_message(user_id, "⚠️ အဆင့် (၂/၃) ⚡️\n\nသင့်အကောင့်မှာ Error / Ban / Issue ပါမပါ ရွေးချယ်ပေးပါ 👇", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("err_"))
def sell_step2_error(call):
    user_id = call.message.chat.id
    err_dict = {
        "err_none": "Error/Issue လုံးဝမရှိ (Clean Account)",
        "err_minor": "Error အနည်းငယ်ရှိပါသည်",
        "err_major": "Ban/Issue ထိဖူးပါသည်"
    }
    user_data[user_id]['error_info'] = err_dict.get(call.data, "မသိရှိပါ")
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔙 ပင်မ Menu သို့ပြန်သွားမည် 🏠", callback_data="back_home"))
    
    msg = bot.send_message(user_id, "💰 အဆင့် (၃/၃) ⚡️\n\nသင် ရောင်းချလိုသော ဈေးနှုန်း (Budget) ကို ဂဏန်းဖြင့် တိုက်ရိုက် ရိုက်ထည့်ပေးပါ ✍️\n(ဥပမာ - 100000 သို့မဟုတ် 250000)", reply_markup=markup)
    bot.register_next_step_handler(msg, process_sell_price_input)

def process_sell_price_input(message):
    user_id = message.chat.id
    if message.text and message.text.startswith('/'):
        return
    try:
        price_val = message.text.replace(",", "").strip()
        int(price_val)
    except ValueError:
        bot.send_message(user_id, "⚠️ ကျေးဇူးပြု၍ မှန်ကန်သော ငွေပမာဏ ဂဏန်းကိုသာ ရိုက်ထည့်ပေးပါ ❌")
        return
        
    user_data[user_id]['expected_price'] = f"{price_val} MMK"
    
    bot.send_message(user_id, "✅ အချက်အလက်များ ရရှိပါပြီ 🔥 Admin ထံသို့ ပေးပို့လိုက်ပါပြီ ခင်ဗျာ ⏳")
    
    data = user_data.get(user_id, {})
    username = message.from_user.username or 'No Username'
    
    admin_msg = f"📥 အကောင့်လာရောင်းသူ ရှိပါသည် ⚡️\n\n👤 User: @{username}\n🆔 User ID: {user_id}\n⚠️ Error/Issue: {data.get('error_info', 'N/A')}\n💰 ရောင်းလိုဈေး: {data.get('expected_price', 'N/A')}\n📸 ပုံအရေအတွက်: {len(data.get('photos', []))} ပုံ"
    
    bot.send_message(ADMIN_ID, admin_msg)
    if data.get('photos'):
        media = [telebot.types.InputMediaPhoto(p) for p in data['photos'][:30]]
        bot.send_media_group(ADMIN_ID, media)

# 5. ADMIN FEATURES (အကောင့်အသစ်တင်ရန် / လက်ကျန်ကြည့်ရန် - ရေရှည်သိမ်းဆည်းမည်)
@bot.message_handler(commands=['admin'])
def admin_command(message):
    if message.from_user.id != ADMIN_ID:
        return
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("👑 အကောင့်အသစ်တင်ရန် ➕", callback_data="admin_add_acc"),
        InlineKeyboardButton("📊 လက်ကျန်အကောင့်များကြည့်ရန် 📂", callback_data="admin_view_acc")
    )
    bot.send_photo(ADMIN_ID, BANNER_WELCOME, caption="👑 [Admin Panel] ⚡️ လိုအပ်သည်များကို ရွေးချယ်ပါ ခင်ဗျာ။", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "admin_add_acc")
def admin_add_account(call):
    if call.message.chat.id != ADMIN_ID:
        return
    msg = bot.send_message(ADMIN_ID, "📝 အကောင့်အသစ် ထည့်သွင်းရန် အချက်အလက်များကို အောက်ပါအတိုင်း ပေးပို့ပါ 👇\n\nအကောင့်နာမည် | Skinအမျိုးအစား | ဈေးနှုန်း\n(ဥပမာ - MLBB Collector | Collector | 150000)")
    bot.register_next_step_handler(msg, process_admin_info)

def process_admin_info(message):
    global acc_counter
    if message.text and message.text.startswith('/'):
        return
    try:
        parts = message.text.split('|')
        title = parts[0].strip()
        skins = parts[1].strip()
        price = int(parts[2].strip())
        
        acc_id = f"ACC-{acc_counter:03d}"
        acc_counter += 1
        
        user_data[ADMIN_ID] = {'id': acc_id, 'title': title, 'skins': skins, 'price': price, 'photos': []}
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ ပုံများတင်ပြီးပါပြီ 🚀", callback_data="admin_save_complete"))
        
        msg = bot.send_message(ADMIN_ID, f"📸 {acc_id} အတွက် ဓာတ်ပုံများကို ဆက်တိုက် ပို့ပေးပါ ⚡️\nပုံများကုန်ပါက အောက်ပါခလုတ်ကို နှိပ်ပါ 👇", reply_markup=markup)
        bot.register_next_step_handler(msg, process_admin_photos_loop)
    except Exception:
        bot.send_message(ADMIN_ID, "⚠️ Format မှားနေပါသည် ❌ /admin ဖြင့် ပြန်စပါ။")

def process_admin_photos_loop(message):
    if message.photo and ADMIN_ID in user_data:
        user_data[ADMIN_ID]['photos'].append(message.photo[-1].file_id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_save_complete")
def admin_save_complete(call):
    data = user_data.get(ADMIN_ID)
    if data:
        accounts_db[data['id']] = {
            'title': data['title'],
            'skins': data['skins'],
            'price': data['price'],
            'photos': data['photos']
        }
        bot.send_message(ADMIN_ID, f"🎉 အောင်မြင်ပါပြီ! {data['id']} အကောင့်ကို Database ထဲသို့ ရေရှည်သိမ်းဆည်းလိုက်ပါပြီ ✅")
        del user_data[ADMIN_ID]

@bot.callback_query_handler(func=lambda call: call.data == "admin_view_acc")
def admin_view_accounts(call):
    if call.message.chat.id != ADMIN_ID:
        return
    if not accounts_db:
        bot.send_message(ADMIN_ID, "📂 လောလောဆယ် လက်ကျန်အကောင့် မရှိသေးပါ။")
        return
        
    for acc_id, acc in accounts_db.items():
        text = f"📂 ID: {acc_id}\n📌 {acc['title']}\n✨ {acc['skins']}\n💵 {acc['price']:,} MMK"
        bot.send_message(ADMIN_ID, text)

# 6. TIPS & TRICKS (Tips ၅ ခုအပြည့်အစုံ ပါဝင်သည်)
@bot.callback_query_handler(func=lambda call: call.data == "show_tips")
def show_tips(call):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔙 ပင်မ Menu သို့ပြန်သွားမည် 🏠", callback_data="back_home"))
    
    tips_text = (
        "💡 Gaming Shop ၏ အသုံးဝင်သော လုံခြုံရေးဆိုင်ရာ အကြံပြုချက် ၅ ချက် ⚡️\n\n"
        "1️⃣ အကောင့်ဝယ်ပြီးပါက Email & Password ချက်ချင်းပြောင်းပါ။\n"
        "2️⃣ 2-Step Verification (နှစ်ဆင့်အတည်ပြုခြင်း) ကို အမြဲဖွင့်ထားပါ။\n"
        "3️⃣ လိမ်လည်မှုများ ကာကွယ်ရန် တရားဝင် Admin နှင့်သာ ငွေလွှဲူလုပ်ဆောင်ပါ။\n"
        "4️⃣ Recovery Email နှင့် Phone Number ကို မိမိပိုင်ဆိုင်ရာသို့ ချက်ချင်းချိတ်ဆက်ပါ။\n"
        "5️⃣ အကောင့်ဝယ်ယူပြီးနောက် အချက်အလက်များကို လုံခြုံစွာ သိမ်းဆည်းထားပါ။"
    )
    bot.send_photo(call.message.chat.id, BANNER_TIPS, caption=tips_text, reply_markup=markup)

if __name__ == "__main__":
    bot.remove_webhook()
    bot.set_webhook(url=f"https://telegram-shop-bot-yiyp.onrender.com/{TELEGRAM_TOKEN}")
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
