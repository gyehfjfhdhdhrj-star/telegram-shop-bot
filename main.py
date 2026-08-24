import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

TELEGRAM_TOKEN = '8614749096:AAE6EY0g2593hpXHmxrOWnhP3d1SgTuDSr4'
ADMIN_ID = 7267372257  

bot = telebot.TeleBot(TELEGRAM_TOKEN)

accounts_db = {}  
user_data = {}    
acc_counter = 1

# 1. START MENU (MULTI-CHOICE MAIN MENU)
@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🛒 အကောင့်ဝယ်မည် 💎", callback_data="buy_acc"),
        InlineKeyboardButton("👀 အကောင့်တွေကြည့်မယ် 🚀", callback_data="browse_acc_0"),
        InlineKeyboardButton("💰 အကောင့်ရောင်းမည် 🔥", callback_data="sell_acc"),
        InlineKeyboardButton("💡 အသုံးဝင်တဲ့ Tips များ 📌", callback_data="show_tips")
    )
    bot.send_message(message.chat.id, "👋 မင်္ဂလာပါ 🎮 Gaming Shop Bot မှ ကြိုဆိုပါတယ် ⚡️\n\nပြုလုပ်လိုသည့် ဝန်ဆောင်မှုကို အောက်ပါ Button များမှ ရွေးချယ်ပေးပါ ခင်ဗျာ 📲", reply_markup=markup)

# 2. TIPS & TRICKS SECTION
@bot.callback_query_handler(func=lambda call: call.data == "show_tips")
def show_tips_menu(call):
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🔒 အကောင့် လုံခြုံရေး 💡", callback_data="tip_security"),
        InlineKeyboardButton("⚡️ အကောင့်မြန်မြန် ရောင်းရရေး 🚀", callback_data="tip_selling"),
        InlineKeyboardButton("🔙 ပင်မ Menu သို့ပြန်သွားမည် 🏠", callback_data="back_home")
    )
    bot.send_message(call.message.chat.id, "💡 Gaming Shop ၏ အသုံးဝင်သော Tips & Tricks များ ⚡️", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("tip_"))
def show_tip_detail(call):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔙 Tips Menu သို့ပြန်သွားမည် 💡", callback_data="show_tips"))
    
    if call.data == "tip_security":
        msg = "🔒 အကောင့်ဝယ်ယူသူများအတွက် လုံခြုံရေး Tip 🛡️\n\n1. အကောင့်ဝယ်ပြီးပါက ချက်ချင်း Moonton Email & Password ပြောင်းပါ 🔐\n2. 2-Step Verification ကို မဖြစ်မနေ အွန်ထားပါ 📲\n3. အခြားစက်များကို Log Out ထုတ်ပါ 🚫"
    else:
        msg = "⚡️ အကောင့် မြန်မြန်ရောင်းရစေမည့် Tip 🚀\n\n1. Skin ဓာတ်ပုံများကို ရှင်းလင်းစွာ ရိုက်ပြပါ 📸\n2. အဓိက Highlight Skin များကို ရှေ့ဆုံးမှ ပြပါ ✨\n3. သင့်တင့်သော ဈေးနှုန်းကို ခန့်မှန်းရွေးချယ်ပါ 💰"
        
    bot.send_message(call.message.chat.id, msg, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "back_home")
def go_home(call):
    send_welcome(call.message)

# 3. ADMIN PANEL (/admin)
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        return
    msg = bot.reply_to(message, "📝 [Admin Panel] 👑\n\nအကောင့်သစ် ထည့်သွင်းရန် အောက်ပါအတိုင်း ခြားပြီး ရိုက်ပေးပါ 👇\n\nအကောင့်နာမည် | Skinအမျိုးအစား | ဈေးနှုန်း\n(ဥပမာ - MLBB Collector | Collector, Legend | 150000)")
    bot.register_next_step_handler(msg, process_admin_add_info)

def process_admin_add_info(message):
    global acc_counter
    try:
        parts = message.text.split('|')
        title = parts[0].strip()
        skins = parts[1].strip()
        price = int(parts[2].strip())
        
        acc_id = f"ACC-{acc_counter:03d}"
        acc_counter += 1
        
        user_data[ADMIN_ID] = {'id': acc_id, 'title': title, 'skins': skins, 'price': price, 'photos': []}
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ ဓာတ်ပုံများ အကုန်ပို့ပြီးပြီ 🚀", callback_data="admin_photos_done"))
        
        msg = bot.reply_to(message, f"📸 {acc_id} အတွက် Skin ဓာတ်ပုံများ ဆက်တိုက် ပို့ပေးပါ ⚡️\n\nဓာတ်ပုံများ အကုန်ပို့ပြီးပါက အောက်ပါ Button ကို နှိပ်ပါ 👇", reply_markup=markup)
        bot.register_next_step_handler(msg, process_admin_add_photos)
    except Exception:
        bot.reply_to(message, "⚠️ Format မှားနေပါတယ် ❌ /admin ကို ပြန်စပေးပါ 🔄")

def process_admin_add_photos(message):
    if message.photo:
        if ADMIN_ID in user_data:
            user_data[ADMIN_ID]['photos'].append(message.photo[-1].file_id)
            bot.register_next_step_handler(message, process_admin_add_photos)

@bot.callback_query_handler(func=lambda call: call.data == "admin_photos_done")
def admin_photos_complete(call):
    data = user_data.get(ADMIN_ID)
    if data:
        accounts_db[data['id']] = {
            'title': data['title'],
            'skins': data['skins'],
            'price': data['price'],
            'photos': data['photos']
        }
        bot.send_message(ADMIN_ID, f"🎉 {data['id']} အကောင့်ကို ပုံပေါင်း ({len(data['photos'])}) ပုံဖြင့် အောင်မြင်စွာ သိမ်းဆည်းလိုက်ပါပြီ ✅")
        del user_data[ADMIN_ID]

# 4. BUY FLOW (MULTIPLE CHOICE SELECTION)
@bot.callback_query_handler(func=lambda call: call.data == "buy_acc")
def buy_step1(call):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✨ Collector Skin 👑", callback_data="filter_collector"),
        InlineKeyboardButton("🌟 Legend Skin 💎", callback_data="filter_legend"),
        InlineKeyboardButton("🔥 Hero / Prime ⚡️", callback_data="filter_hero"),
        InlineKeyboardButton("🌈 အကုန်လုံး ကြည့်မည် 🚀", callback_data="filter_all")
    )
    bot.send_message(call.message.chat.id, "❓ ကြိုက်နှစ်သက်သော Skin အမျိုးအစား ကို ရွေးချယ်ပေးပါ 🎯", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("filter_"))
def buy_step2(call):
    skin_pref = call.data.replace("filter_", "")
    user_id = call.message.chat.id
    user_data[user_id] = {'skin_pref': skin_pref}
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("💰 50,000 MMK အောက် 📉", callback_data="budget_50000"),
        InlineKeyboardButton("💰 150,000 MMK အောက် 📊", callback_data="budget_150000"),
        InlineKeyboardButton("💰 300,000 MMK အောက် 📈", callback_data="budget_300000"),
        InlineKeyboardButton("💎 Budget အကန့်အသတ်မရှိ 🚀", callback_data="budget_9999999")
    )
    bot.send_message(user_id, "💰 သုံးစွဲလိုသော Budget ပမာဏ ကို ရွေးချယ်ပေးပါ 🎯", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("budget_"))
def buy_step3(call):
    user_id = call.message.chat.id
    max_price = int(call.data.replace("budget_", ""))
    skin_pref = user_data.get(user_id, {}).get('skin_pref', 'all')
    
    matched = []
    for acc_id, acc in accounts_db.items():
        if acc['price'] <= max_price:
            if skin_pref == 'all' or skin_pref in acc['skins'].lower():
                matched.append((acc_id, acc))
    
    if not matched:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 ပင်မ Menu သို့ပြန်သွားမည် 🏠", callback_data="back_home"))
        bot.send_message(user_id, "❌ စိတ်မကောင်းပါ၊ သင့် လိုအပ်ချက်နှင့် ကိုက်ညီသော အကောင့် မရှိသေးပါ ခင်ဗျာ 😔", reply_markup=markup)
        return
    
    bot.send_message(user_id, f"🎯 သင့်အတွက် ကိုက်ညီသော အကောင့် ({len(matched)}) ခု တွေ့ရှိပါသည် ⚡️")
    for acc_id, acc in matched:
        text = f"🆔 {acc_id} - {acc['title']}\n✨ Skins: {acc['skins']}\n💵 ဈေးနှုန်း: {acc['price']:,} MMK"
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("🔍 အသေးစိတ် ကြည့်မည် 📸", callback_data=f"detail_{acc_id}"),
            InlineKeyboardButton("🛒 အကောင့်ဝယ်မည် 💎", callback_data=f"confirm_buy_{acc_id}")
        )
        bot.send_message(user_id, text, reply_markup=markup)

# 5. BROWSE FLOW (LOOK sample + MENU 3 CHOICE)
@bot.callback_query_handler(func=lambda call: call.data.startswith("browse_acc_"))
def browse_accounts(call):
    idx = int(call.data.split("_")[2])
    acc_keys = list(accounts_db.keys())
    
    if not acc_keys:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 ပင်မ Menu သို့ပြန်သွားမည် 🏠", callback_data="back_home"))
        bot.send_message(call.message.chat.id, "❌ လောလောဆယ် ပြသရန် အကောင့် မရှိသေးပါ ခင်ဗျာ 😔", reply_markup=markup)
        return
    
    if idx >= len(acc_keys):
        idx = 0
        
    acc_id = acc_keys[idx]
    acc = accounts_db[acc_id]
    
    photos = acc['photos'][:5]
    if photos:
        media = [telebot.types.InputMediaPhoto(p) for p in photos]
        bot.send_media_group(call.message.chat.id, media)
        
    text = f"📌 အကောင့် ID: {acc_id}\n📝 {acc['title']}\n✨ Skins: {acc['skins']}\n💵 ဈေးနှုန်း: {acc['price']:,} MMK"
    
    markup = InlineKeyboardMarkup(row_width=1)
    next_idx = idx + 1 if (idx + 1) < len(acc_keys) else 0
    markup.add(
        InlineKeyboardButton("➡️ နောက်အကောင့်ဆက်ကြည့်မည် 🚀", callback_data=f"browse_acc_{next_idx}"),
        InlineKeyboardButton("🔍 အသေးစိတ် ကြည့်မည် 📸", callback_data=f"detail_{acc_id}"),
        InlineKeyboardButton("🛒 အကောင့်ဝယ်မည် 💎", callback_data=f"confirm_buy_{acc_id}")
    )
    bot.send_message(call.message.chat.id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("detail_"))
def view_detail(call):
    acc_id = call.data.replace("detail_", "")
    acc = accounts_db.get(acc_id)
    if acc:
        bot.send_message(call.message.chat.id, f"🔍 {acc_id} အသေးစိတ် ဓာတ်ပုံများ ({len(acc['photos'])} ပုံ) 📸")
        media = [telebot.types.InputMediaPhoto(p) for p in acc['photos'][:30]]
        bot.send_media_group(call.message.chat.id, media)

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_buy_"))
def confirm_buy(call):
    acc_id = call.data.replace("confirm_buy_", "")
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("👨‍💻 Admin ထံ တိုက်ရိုက်သွားမည် 🚀", url="https://t.me/your_admin_username"))
    bot.send_message(call.message.chat.id, f"✅ {acc_id} အကောင့်ကို ဝယ်ယူရန် Admin ထံ တိုက်ရိုက် ဆက်သွယ်နိုင်ပါပြီ ခင်ဗျာ 💎", reply_markup=markup)

# 6. SELL FLOW (MULTIPLE CHOICE + SAVE AFTER DONE BUTTON)
@bot.callback_query_handler(func=lambda call: call.data == "sell_acc")
def sell_step1(call):
    user_id = call.message.chat.id
    user_data[user_id] = {'photos': []}
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ ဓာတ်ပုံများ အကုန်ပို့ပြီးပြီ 🚀", callback_data="sell_photos_done"))
    
    msg = bot.send_message(user_id, "📸 အဆင့် (၁/၃) ⚡️\n\nသင့်အကောင့်၏ Skin ဓာတ်ပုံများကို ဆက်တိုက် ပို့ပေးပါ 📲\n\nပုံများ အကုန်ပို့ပြီးပါက အောက်ပါ Button ကို နှိပ်ပါ 👇", reply_markup=markup)
    bot.register_next_step_handler(msg, collect_sell_photos)

def collect_sell_photos(message):
    user_id = message.chat.id
    if user_id not in user_data:
        user_data[user_id] = {'photos': []}
        
    if message.photo:
        user_data[user_id]['photos'].append(message.photo[-1].file_id)
        bot.register_next_step_handler(message, collect_sell_photos)

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
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("💰 50,000 MMK 📉", callback_data="price_50000"),
        InlineKeyboardButton("💰 100,000 MMK 📊", callback_data="price_100000"),
        InlineKeyboardButton("💰 200,000 MMK 📈", callback_data="price_200000"),
        InlineKeyboardButton("💰 300,000 MMK+ 🔥", callback_data="price_300000+")
    )
    bot.send_message(user_id, "💰 အဆင့် (၃/၃) ⚡️\n\nသင် ရောင်းချလိုသော ခန့်မှန်း ဈေးနှုန်း (Price) ကို ရွေးချယ်ပေးပါ 👇", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("price_"))
def sell_step3_price(call):
    user_id = call.message.chat.id
    price_val = call.data.replace("price_", "")
    user_data[user_id]['expected_price'] = f"{price_val} MMK"
    
    bot.send_message(user_id, "✅ အချက်အလက် ၃ ခုစလုံး ရရှိပါပြီ 🔥 Admin ၏ အတည်ပြုချက်ကို ခဏ စောင့်ဆိုင်းပေးပါ ခင်ဗျာ ⏳")
    
    data = user_data.get(user_id, {})
    username = call.from_user.username or 'No Username'
    
    admin_msg = f"📥 အကောင့်လာရောင်းသူ ရှိပါသည် ⚡️\n\n👤 User: @{username}\n🆔 User ID: {user_id}\n⚠️ Error/Issue: {data.get('error_info', 'N/A')}\n💰 ရောင်းလိုဈေး: {data.get('expected_price', 'N/A')}\n📸 ပုံအရေအတွက်: {len(data.get('photos', []))} ပုံ"
    
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ လက်ခံမည် 💎", callback_data=f"app_{user_id}"),
        InlineKeyboardButton("❌ ငြင်းပယ်မည် 🚫", callback_data=f"rej_{user_id}")
    )
    
    bot.send_message(ADMIN_ID, admin_msg, reply_markup=markup)
    if data.get('photos'):
        media = [telebot.types.InputMediaPhoto(p) for p in data['photos'][:30]]
        bot.send_media_group(ADMIN_ID, media)

# 7. ADMIN ACTION (ACCEPT / REJECT)
@bot.callback_query_handler(func=lambda call: call.data.startswith(("app_", "rej_")))
def handle_admin_decision(call):
    prefix, seller_id = call.data.split("_")
    seller_id = int(seller_id)
    
    if prefix == "app":
        bot.answer_callback_query(call.id, "လက်ခံလိုက်ပါပြီ ✅")
        bot.send_message(ADMIN_ID, f"✅ [ACCEPTED] User ID {seller_id} ၏ အကောင့်အား လက်ခံလိုက်ပါပြီ 🔥")
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("👨‍💻 Admin ထံ တိုက်ရိုက်သွားမည် 🚀", url="https://t.me/your_admin_username"))
        bot.send_message(seller_id, "🎉 မင်္ဂလာပါ! သင့်အကောင့်အား ရောင်းချရန် Admin မှ လက်ခံလိုက်ပါပြီ ✅\n\nကျေးဇူးပြု၍ အောက်ပါ ခလုတ်မှတစ်ဆင့် Admin ထံ တိုက်ရိုက် ဆက်သွယ်ပေးပါ ခင်ဗျာ 💎", reply_markup=markup)
    else:
        bot.answer_callback_query(call.id, "ငြင်းပယ်လိုက်ပါပြီ ❌")
        bot.send_message(ADMIN_ID, f"❌ [REJECTED] User ID {seller_id} ၏ အကောင့်အား ငြင်းပယ်လိုက်ပါပြီ 🚫")
        bot.send_message(seller_id, "😔 စိတ်မကောင်းပါ။ သင့်အကောင့်အား ရောင်းချရေးအတွက် Admin မှ လက်မခံပါ/ငြင်းပယ်လိုက်ပါသည် 🚫")

bot.infinity_polling()
