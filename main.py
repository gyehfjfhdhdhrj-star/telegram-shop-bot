import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

TELEGRAM_TOKEN = '8614749096:AAE6EY0g2593hpXHmxrOWnhP3d1SgTuDSr4'
ADMIN_ID = 7267372257  # Admin ရဲ့ Telegram User ID (Integer)

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Accounts Database Structure:
# { "ACC-001": {"title": "...", "price": "...", "details": "...", "photos": [...] } }
accounts_db = {}
user_data = {}
admin_temp = {}

# 1. START MENU
@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = InlineKeyboardMarkup()
    markup.row_width = 2
    markup.add(
        InlineKeyboardButton("🛒 အကောင့်ကြည့်မည် / ဝယ်မည်", callback_data="buy_acc"),
        InlineKeyboardButton("💰 အကောင့်ရောင်းမည်", callback_data="sell_acc")
    )
    bot.send_message(message.chat.id, "မင်္ဂလာပါ! Telegram Shop Bot မှ ကြိုဆိုပါတယ်။\nအောက်ပါ Menu မှ ရွေးချယ်ပေးပါ-", reply_markup=markup)

# 2. ADMIN MENU: /admin (အကောင့်ထည့်/ဖျက်/စစ်ရန်)
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⚠️ သင်သည် Admin မဟုတ်ပါ။")
        return
    
    markup = InlineKeyboardMarkup()
    markup.row_width = 2
    markup.add(
        InlineKeyboardButton("➕ အကောင့်သစ်တင်မည်", callback_data="admin_add_acc"),
        InlineKeyboardButton("📋 အကောင့်အားလုံးစစ်မည်", callback_data="admin_list_acc")
    )
    bot.send_message(ADMIN_ID, "🛠️ **Admin Control Panel**", reply_markup=markup, parse_mode="Markdown")

# ADMIN ADD ACCOUNT FLOW
@bot.callback_query_handler(func=lambda call: call.data == "admin_add_acc")
def admin_add_start(call):
    if call.from_user.id != ADMIN_ID:
        return
    msg = bot.send_message(ADMIN_ID, "📝 **အဆင့် (၁/၃):** အကောင့် ID သို့မဟုတ် နာမည် ထည့်ပါ (ဥပမာ - `ACC-01` သို့မဟုတ် `MLBB Collector`):", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_acc_id)

def process_acc_id(message):
    acc_id = message.text.strip()
    admin_temp[ADMIN_ID] = {'id': acc_id, 'photos': []}
    msg = bot.reply_to(message, "📝 **အဆင့် (၂/၃):** အကောင့် အသေးစိတ် စာရိုက်ထည့်ပါ (ဥပမာ - `Skins: 120 (Collector 2, Legend 1) | Price: 80,000 MMK`):", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_acc_details)

def process_acc_details(message):
    admin_temp[ADMIN_ID]['details'] = message.text
    msg = bot.reply_to(message, "📸 **အဆင့် (၃/၃):** အကောင့်ရဲ့ Skin ဓာတ်ပုံများ (ပုံ ၃၀ အထိ) ပို့ပေးပါ။ ပို့ပြီးပါက **'ပြီးပြီ'** ဟု စာရိုက်ပို့ပါ။")
    bot.register_next_step_handler(msg, process_acc_photos)

def process_acc_photos(message):
    if message.text and message.text.strip() == "ပြီးပြီ":
        acc_id = admin_temp[ADMIN_ID]['id']
        details = admin_temp[ADMIN_ID]['details']
        photos = admin_temp[ADMIN_ID]['photos']
        
        accounts_db[acc_id] = {
            'details': details,
            'photos': photos
        }
        bot.send_message(ADMIN_ID, f"✅ **အကောင့် `{acc_id}` ကို သိမ်းဆည်းလိုက်ပါပြီ!**\n\nပုံပေါင်း: {len(photos)} ပုံ", parse_mode="Markdown")
        del admin_temp[ADMIN_ID]
        return
    
    if message.photo:
        photo_id = message.photo[-1].file_id
        admin_temp[ADMIN_ID]['photos'].append(photo_id)
        count = len(admin_temp[ADMIN_ID]['photos'])
        msg = bot.send_message(ADMIN_ID, f"📸 ပုံ {count}/30 ရပြီးပါပြီ။ ထပ်ပို့ပါ (သို့မဟုတ် **'ပြီးပြီ'** ဟု ရိုက်ပါ)။")
        bot.register_next_step_handler(msg, process_acc_photos)
    else:
        msg = bot.send_message(ADMIN_ID, "⚠️ ဓာတ်ပုံ ပို့ပေးပါ သို့မဟုတ် **'ပြီးပြီ'** ဟု ရိုက်ပို့ပါ။")
        bot.register_next_step_handler(msg, process_acc_photos)

# 3. ADMIN LIST / SHOW ACCOUNTS
@bot.callback_query_handler(func=lambda call: call.data.startswith("view_acc_"))
def view_single_account(call):
    acc_id = call.data.replace("view_acc_", "")
    if acc_id in accounts_db:
        acc = accounts_db[acc_id]
        bot.send_message(call.message.chat.id, f"📌 **ID:** `{acc_id}`\nℹ️ **အသေးစိတ်:**\n{acc['details']}", parse_mode="Markdown")
        if acc['photos']:
            media_group = [telebot.types.InputMediaPhoto(p) for p in acc['photos'][:30]]
            bot.send_media_group(call.message.chat.id, media_group)
    else:
        bot.send_message(call.message.chat.id, "❌ ဤအကောင့် မရှိတော့ပါ။")

# 4. BUYER FLOW (ဝယ်သူများ အကောင့်စာရင်း ကြည့်ခြင်း)
@bot.callback_query_handler(func=lambda call: call.data in ["buy_acc", "admin_list_acc"])
def list_accounts(call):
    if not accounts_db:
        bot.send_message(call.message.chat.id, "❌ လက်ရှိတွင် သိမ်းဆည်းထားသော အကောင့်များ မရှိသေးပါ။")
        return
    
    markup = InlineKeyboardMarkup()
    for acc_id, data in accounts_db.items():
        markup.add(InlineKeyboardButton(f"🆔 {acc_id}", callback_data=f"view_acc_{acc_id}"))
    
    bot.send_message(call.message.chat.id, "🛒 **ရရှိနိုင်သော အကောင့်စာရင်း (ပုံနှင့် အသေးစိတ်ကြည့်ရန် နှိပ်ပါ):**", reply_markup=markup, parse_mode="Markdown")

# 5. SELL FLOW (အကောင့်လာရောင်းသူများ Skin ပုံ ပို့ရန်)
@bot.callback_query_handler(func=lambda call: call.data == "sell_acc")
def sell_account_start(call):
    user_id = call.message.chat.id
    user_data[user_id] = {'photos': []}
    msg = bot.send_message(user_id, "📸 သင့်အကောင့်၏ Skin ဓာတ်ပုံများကို ပို့ပေးပါ။ (ပုံပေါင်း ၃၀ အထိ ပို့နိုင်ပါသည်)\n\nပုံများ ပို့ပြီးပါက **'ပြီးပြီ'** ဟု စာရိုက်၍ ပို့ပေးပါ။")
    bot.register_next_step_handler(msg, collect_seller_photos)

def collect_seller_photos(message):
    user_id = message.chat.id
    if user_id not in user_data:
        return

    if message.text and message.text.strip() == "ပြီးပြီ":
        photos = user_data[user_id]['photos']
        if not photos:
            bot.send_message(user_id, "⚠️ ဓာတ်ပုံ မပို့ရသေးပါ။ ကျေးဇူးပြု၍ ပုံများ ပို့ပေးပါ။")
            bot.register_next_step_handler(message, collect_seller_photos)
            return
        
        bot.send_message(user_id, f"✅ Skin ဓာတ်ပုံ {len(photos)} ပုံကို Admin ထံသို့ ပေးပို့လိုက်ပါပြီ။")
        
        bot.send_message(ADMIN_ID, f"📥 **အကောင့်လာရောင်းသူ ရှိပါသည်!**\nUser: @{message.from_user.username or 'No Username'}\nUser ID: `{user_id}`", parse_mode="Markdown")
        media_group = [telebot.types.InputMediaPhoto(p) for p in photos[:30]]
        bot.send_media_group(ADMIN_ID, media_group)
        del user_data[user_id]
        return

    if message.photo:
        user_data[user_id]['photos'].append(message.photo[-1].file_id)
        count = len(user_data[user_id]['photos'])
        if count >= 30:
            bot.send_message(user_id, "⚠️ ဓာတ်ပုံ ၃၀ ပြည့်သွားပါပြီ။ Admin ထံသို့ ပေးပို့လိုက်ပါပြီ။")
            bot.send_message(ADMIN_ID, f"📥 **အကောင့်လာရောင်းသူ ရှိပါသည် (ပုံ ၃၀ ပြည့်)!**\nUser: @{message.from_user.username or 'No Username'}", parse_mode="Markdown")
            media_group = [telebot.types.InputMediaPhoto(p) for p in user_data[user_id]['photos']]
            bot.send_media_group(ADMIN_ID, media_group)
            del user_data[user_id]
        else:
            msg = bot.send_message(user_id, f"📸 ပုံ {count}/30 ရရှိပါပြီ။ ထပ်ပို့ပါ (သို့မဟုတ် **'ပြီးပြီ'** ဟု ရိုက်ပို့ပါ)။")
            bot.register_next_step_handler(msg, collect_seller_photos)

bot.infinity_polling()
