import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

TELEGRAM_TOKEN = '8614749096:AAE6EY0g2593hpXHmxrOWnhP3d1SgTuDSr4'
ADMIN_ID = 7267372257  # Admin ရဲ့ Telegram User ID

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Data Stores
accounts_db = {}  # Admin တင်ထားသော အကောင့်များ
user_data = {}    # ဝယ်သူ/ရောင်းသူ အချက်အလက်များ Temp သိမ်းရန်
acc_counter = 1

# 1. START MENU (Menu ၃ ခု)
@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🛒 အကောင့်ဝယ်မည်", callback_data="buy_acc"),
        InlineKeyboardButton("👀 အကောင့်တွေကြည့်မယ်", callback_data="browse_acc_0"),
        InlineKeyboardButton("💰 အကောင့်ရောင်းမည်", callback_data="sell_acc")
    )
    bot.send_message(message.chat.id, "မင်္ဂလာပါ! Telegram Shop Bot မှ ကြိုဆိုပါတယ်။\nပြုလုပ်လိုသည့် ဝန်ဆောင်မှုကို ရွေးချယ်ပါ-", reply_markup=markup)

# 2. ADMIN COMMANDS (/admin & /addacc)
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        return
    msg = bot.reply_to(message, "📝 **[Admin] အကောင့်သစ်ထည့်ရန်**\n\nအောက်ပါ format အတိုင်း ရိုက်ထည့်ပါ-\n`အကောင့်အမည် | Skinအမျိုးအစား | ဈေးနှုန်း`\n(ဥပမာ- `MLBB Collector | Collector, Legend | 150000`)", parse_mode="Markdown")
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
        msg = bot.reply_to(message, f"📸 **{acc_id}** အတွက် Skin ဓာတ်ပုံ ၅ ပုံ (သို့ ၃၀ အထိ) ပို့ပေးပါ။ ပို့ပြီးပါက **'ပြီးပြီ'** ဟု ရိုက်ပို့ပါ။")
        bot.register_next_step_handler(msg, process_admin_add_photos)
    except Exception as e:
        bot.reply_to(message, "⚠️ Format မှားယွင်းနေပါသည်။ `/admin` ကို ပြန်စပါ။")

def process_admin_add_photos(message):
    if message.text and message.text.strip() == "ပြီးပြီ":
        data = user_data[ADMIN_ID]
        accounts_db[data['id']] = {
            'title': data['title'],
            'skins': data['skins'],
            'price': data['price'],
            'photos': data['photos']
        }
        bot.send_message(ADMIN_ID, f"✅ **{data['id']}** ကို အောင်မြင်စွာ သိမ်းဆည်းလိုက်ပါပြီ။")
        del user_data[ADMIN_ID]
        return
    
    if message.photo:
        user_data[ADMIN_ID]['photos'].append(message.photo[-1].file_id)
        msg = bot.send_message(ADMIN_ID, f"📸 ပုံ {len(user_data[ADMIN_ID]['photos'])} ပုံ ရပြီးပါပြီ။ ထပ်ပို့ပါ (သို့မဟုတ် **'ပြီးပြီ'** ဟု ရိုက်ပါ)။")
        bot.register_next_step_handler(msg, process_admin_add_photos)

# 3. BUY FLOW (အကောင့်ဝယ်မည် - စကင်နှင့် ဈေးနှုန်း မေးခြင်း)
@bot.callback_query_handler(func=lambda call: call.data == "buy_acc")
def buy_step1(call):
    user_id = call.message.chat.id
    user_data[user_id] = {}
    msg = bot.send_message(user_id, "❓ ဘယ်လို **Skin အမျိုးအစား** ကြိုက်ပါသလဲ? (ဥပမာ - Collector, Legend, Hero သို့မဟုတ် 'အကုန်'):")
    bot.register_next_step_handler(msg, buy_step2)

def buy_step2(message):
    user_id = message.chat.id
    user_data[user_id]['skin_pref'] = message.text.strip().lower()
    msg = bot.reply_to(message, "💰 အကောင့်အတွက် **Budget (ဘတ်ဂျက်/ဈေးနှုန်း)** ဘယ်လောက် ပမာဏ သုံးချင်ပါသလဲ? (ဥပမာ - 100000):")
    bot.register_next_step_handler(msg, buy_step3)

def buy_step3(message):
    user_id = message.chat.id
    try:
        max_price = int(message.text.strip())
        skin_pref = user_data[user_id].get('skin_pref', '')
        
        matched = []
        for acc_id, acc in accounts_db.items():
            if acc['price'] <= max_price:
                if skin_pref == 'အကုန်' or skin_pref in acc['skins'].lower():
                    matched.append((acc_id, acc))
        
        if not matched:
            bot.send_message(user_id, "❌ သင်လိုချင်သော စကင်/ဈေးနှုန်းနှင့် ကိုက်ညီသည့် အကောင့် မရှိသေးပါ။")
            return
        
        bot.send_message(user_id, f"🎯 **သင့်လိုအပ်ချက်နှင့် ကိုက်ညီသော အကောင့် ({len(matched)}) ခု တွေ့ရှိပါသည်:**")
        for acc_id, acc in matched:
            text = f"🆔 **{acc_id}** - {acc['title']}\n✨ Skins: {acc['skins']}\n💵 ဈေးနှုန်း: {acc['price']:,} MMK"
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("🔍 အသေးစိတ် ကြည့်မည်", callback_data=f"detail_{acc_id}"),
                InlineKeyboardButton("🛒 အကောင့်ဝယ်မည်", callback_data=f"confirm_buy_{acc_id}")
            )
            bot.send_message(user_id, text, reply_markup=markup, parse_mode="Markdown")
            
    except ValueError:
        bot.send_message(user_id, "⚠️ ဈေးနှုန်းကို ဂဏန်းသီးသန့် ရိုက်ထည့်ပေးပါ။ ပြန်စရန် /start နှိပ်ပါ။")

# 4. BROWSE FLOW (အကောင့်များ ကြည့်မည် - 5 ပုံ နမူနာ + Menu 3 ခု)
@bot.callback_query_handler(func=lambda call: call.data.startswith("browse_acc_"))
def browse_accounts(call):
    idx = int(call.data.split("_")[2])
    acc_keys = list(accounts_db.keys())
    
    if not acc_keys:
        bot.send_message(call.message.chat.id, "❌ လောလောဆယ် ပြသရန် အကောင့် မရှိသေးပါ။")
        return
    
    if idx >= len(acc_keys):
        idx = 0 # ပြန်စမည်
        
    acc_id = acc_keys[idx]
    acc = accounts_db[acc_id]
    
    # ပထမ ၅ ပုံ ပြခြင်း
    photos = acc['photos'][:5]
    if photos:
        media = [telebot.types.InputMediaPhoto(p) for p in photos]
        bot.send_media_group(call.message.chat.id, media)
        
    text = f"📌 **အကောင့်:** {acc_id}\n📝 {acc['title']}\n✨ Skins: {acc['skins']}\n💵 ဈေးနှုန်း: {acc['price']:,} MMK"
    
    markup = InlineKeyboardMarkup(row_width=1)
    next_idx = idx + 1 if (idx + 1) < len(acc_keys) else 0
    markup.add(
        InlineKeyboardButton("➡️ နောက်အကောင့်ဆက်ကြည့်မည်", callback_data=f"browse_acc_{next_idx}"),
        InlineKeyboardButton("🔍 အကောင့်ကို အသေးစိတ်ကြည့်မည်", callback_data=f"detail_{acc_id}"),
        InlineKeyboardButton("🛒 အကောင့်ဝယ်မည်", callback_data=f"confirm_buy_{acc_id}")
    )
    bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode="Markdown")

# Detail & Buy Confirm
@bot.callback_query_handler(func=lambda call: call.data.startswith("detail_"))
def view_detail(call):
    acc_id = call.data.replace("detail_", "")
    acc = accounts_db.get(acc_id)
    if acc:
        bot.send_message(call.message.chat.id, f"🔍 **{acc_id} အသေးစိတ် ဓာတ်ပုံများ ({len(acc['photos'])} ပုံ):**")
        media = [telebot.types.InputMediaPhoto(p) for p in acc['photos'][:30]]
        bot.send_media_group(call.message.chat.id, media)

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_buy_"))
def confirm_buy(call):
    acc_id = call.data.replace("confirm_buy_", "")
    bot.send_message(call.message.chat.id, f"✅ **{acc_id}** ကို ဝယ်ယူရန် စိတ်ဝင်စားသည့်အတွက် ကျေးဇူးတင်ပါသည်။ Admin ထံ တိုက်ရိုက် ဆက်သွယ်ပေးပါ။\n\n👨‍💻 Admin: @your_admin_username")

# 5. SELL FLOW (၃ ဆင့် ပြီးမှ Admin ဆီ ပို့ခြင်း + Approve/Reject)
@bot.callback_query_handler(func=lambda call: call.data == "sell_acc")
def sell_step1(call):
    user_id = call.message.chat.id
    user_data[user_id] = {'photos': []}
    msg = bot.send_message(user_id, "📸 **အဆင့် (၁/၃):** သင့်အကောင့်၏ Skin ဓာတ်ပုံများကို ပို့ပေးပါ။ ပို့ပြီးပါက **'ပြီးပြီ'** ဟု စာရိုက်ပို့ပေးပါ။")
    bot.register_next_step_handler(msg, collect_sell_photos)

def collect_sell_photos(message):
    user_id = message.chat.id
    if message.text and message.text.strip() == "ပြီးပြီ":
        if not user_data[user_id]['photos']:
            msg = bot.send_message(user_id, "⚠️ ဓာတ်ပုံ မပို့ရသေးပါ။ ပုံများ ပို့ပေးပါ:")
            bot.register_next_step_handler(msg, collect_sell_photos)
            return
        
        # အဆင့် ၂ မေးမည်
        msg = bot.send_message(user_id, "⚠️ **အဆင့် (၂/၃):** သင့်အကောင့်မှာ **Error / Ban / Issue** တစ်စုံတစ်ရာ ပါမပါ ရေးပေးပါ:")
        bot.register_next_step_handler(msg, sell_step2_error)
        return

    if message.photo:
        user_data[user_id]['photos'].append(message.photo[-1].file_id)
        msg = bot.send_message(user_id, f"📸 ပုံ {len(user_data[user_id]['photos'])} ပုံ လက်ခံရရှိပါပြီ။ ထပ်ပို့နိုင်ပါသည် (သို့မဟုတ် **'ပြီးပြီ'** ဟု ရိုက်ပို့ပါ)။")
        bot.register_next_step_handler(msg, collect_sell_photos)

def sell_step2_error(message):
    user_id = message.chat.id
    user_data[user_id]['error_info'] = message.text
    msg = bot.reply_to(message, "💰 **အဆင့် (၃/၃):** သင်ရောင်းချလိုသော **ခန့်မှန်း ဈေးနှုန်း (Price)** ကို ရေးပေးပါ:")
    bot.register_next_step_handler(msg, sell_step3_price)

def sell_step3_price(message):
    user_id = message.chat.id
    user_data[user_id]['expected_price'] = message.text
    
    bot.send_message(user_id, "✅ အချက်အလက် ၃ ခုစလုံး ရရှိပါပြီ။ Admin ၏ အတည်ပြုချက်ကို စောင့်ဆိုင်းပေးပါ။")
    
    # Admin ထံ ၃ ဆင့်လုံး ပို့ခြင်း
    data = user_data[user_id]
    username = message.from_user.username or 'No Username'
    
    admin_msg = f"📥 **အကောင့်လာရောင်းသူ ရှိပါသည်!**\n\n👤 User: @{username}\n🆔 User ID: `{user_id}`\n⚠️ Error/Issue: {data['error_info']}\n💰 ရောင်းလိုဈေး: {data['expected_price']}"
    
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ လက်ခံမည်", callback_data=f"approve_{user_id}"),
        InlineKeyboardButton("❌ ငြင်းပယ်မည်", callback_data=f"reject_{user_id}")
    )
    
    bot.send_message(ADMIN_ID, admin_msg, reply_markup=markup, parse_mode="Markdown")
    if data['photos']:
        media = [telebot.types.InputMediaPhoto(p) for p in data['photos'][:30]]
        bot.send_media_group(ADMIN_ID, media)

# Admin Approve/Reject Action
@bot.callback_query_handler(func=lambda call: call.data.startswith(("approve_", "reject_")))
def handle_admin_decision(call):
    action, seller_id = call.data.split("_")
    seller_id = int(seller_id)
    
    if action == "approve":
        bot.answer_callback_query(call.id, "လက်ခံလိုက်ပါပြီ")
        bot.edit_message_text(f"{call.message.text}\n\n✅ **[ADMIN ACTION: ACCEPTED]**", ADMIN_ID, call.message.message_id)
        bot.send_message(seller_id, "🎉 **မင်္ဂလာပါ! သင့်အကောင့်အား ရောင်းချရန် Admin မှ လက်ခံလိုက်ပါပြီ။**\nဆက်လက် ဆောင်ရွက်နိုင်ရန် Admin ထံ တိုက်ရိုက် ဆက်သွယ်ပေးပါ။\n👨‍💻 Admin: @your_admin_username")
    else:
        bot.answer_callback_query(call.id, "ငြင်းပယ်လိုက်ပါပြီ")
        bot.edit_message_text(f"{call.message.text}\n\n❌ **[ADMIN ACTION: REJECTED]**", ADMIN_ID, call.message.message_id)
        bot.send_message(seller_id, "😔 **စိတ်မကောင်းပါ။ သင့်အကောင့်အား ရောင်းချရေးအတွက် Admin မှ လက်မခံပါ/ငြင်းပယ်လိုက်ပါသည်။**")
