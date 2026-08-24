import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# မိမိ၏ Token နှင့် Admin Chat ID များကို ဒီနေရာတွင် တိုက်ရိုက် ထည့်ပါ
TELEGRAM_TOKEN = 'YOUR_TELEGRAM_TOKEN'
ADMIN_ID = 'YOUR_ADMIN_CHAT_ID'  # ID ကို String အနေဖြင့် ထည့်ပါ (ဥပမာ '123456789')

bot = telebot.TeleBot(TELEGRAM_TOKEN)
user_sell_data = {}

# START MENU
@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = InlineKeyboardMarkup()
    markup.row_width = 2
    markup.add(
        InlineKeyboardButton("🛒 အကောင့်ဝယ်မည်", callback_data="buy_acc"),
        InlineKeyboardButton("💰 အကောင့်ရောင်းမည်", callback_data="sell_acc")
    )
    bot.send_message(message.chat.id, "မင်္ဂလာပါ! အကောင့် ဝယ်ယူလိုပါသလား သို့မဟုတ် ရောင်းချလိုပါသလား။", reply_markup=markup)

# SELL FLOW
@bot.callback_query_handler(func=lambda call: call.data == "sell_acc")
def sell_start(call):
    chat_id = call.message.chat.id
    user_sell_data[chat_id] = {}
    msg = bot.send_message(chat_id, "📌 **အဆင့် (၁)**\nသင်ရောင်းချချင်သော Account ရဲ့ အသေးစိတ် (Game ID, Level, Skins) ကို ရိုက်ပို့ပေးပါ။")
    bot.register_next_step_handler(msg, step_get_info)

def step_get_info(message):
    chat_id = message.chat.id
    user_sell_data[chat_id]['info'] = message.text
    msg = bot.send_message(chat_id, "💰 **အဆင့် (၂)**\nသင်လိုချင်သော မျှော်မှန်းစျေးနှုန်းကို ရိုက်ထည့်ပေးပါ။ (ဥပမာ - 45000 Ks)")
    bot.register_next_step_handler(msg, step_get_price)

def step_get_price(message):
    chat_id = message.chat.id
    user_sell_data[chat_id]['expected_price'] = message.text
    
    markup = InlineKeyboardMarkup()
    markup.row_width = 2
    markup.add(
        InlineKeyboardButton("✅ Clean (No Error)", callback_data="err_clean"),
        InlineKeyboardButton("⚠️ Moonton Error", callback_data="err_moonton"),
        InlineKeyboardButton("⚠️ 3rd Party Error", callback_data="err_3rd"),
        InlineKeyboardButton("⚠️ Both Errors", callback_data="err_both")
    )
    bot.send_message(chat_id, "⚠️ **အဆင့် (၃)**\nအကောင့်မှာ မည်သည့် Error ပါဝင်ပါသလဲ။", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("err_"))
def step_get_error_and_finish(call):
    chat_id = call.message.chat.id
    error_dict = {
        "err_clean": "Clean (No Error)",
        "err_moonton": "Moonton Error ပါသည်",
        "err_3rd": "3rd Party Error ပါသည်",
        "err_both": "Moonton + 3rd Error ပါသည်"
    }
    selected_error = error_dict.get(call.data, "N/A")
    info = user_sell_data.get(chat_id, {}).get('info', 'N/A')
    expected_price = user_sell_data.get(chat_id, {}).get('expected_price', 'N/A')
    user_username = call.from_user.username or "Username မရှိပါ"

    bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="✅ **အချက်အလက်များ လက်ခံရရှိပါပြီ။** Admin ဘက်မှ စျေးနှုန်း စစ်ဆေးပြီးပါက ပြန်လည် ဆက်သွယ်ပေးပါမည်။")

    admin_notification = (
        f"📩 **အကောင့်ရောင်းရန် ရောက်ရှိလာပါသည်**\n\n"
        f"👤 **User:** @{user_username} (ID: `{chat_id}`)\n"
        f"📝 **Info:** {info}\n"
        f"💵 **မျှော်မှန်းစျေး:** {expected_price}\n"
        f"⚠️ **Error Status:** {selected_error}"
    )
    bot.send_message(ADMIN_ID, admin_notification)
    if chat_id in user_sell_data: del user_sell_data[chat_id]

# BUY FLOW (PLACEHOLDER)
@bot.callback_query_handler(func=lambda call: call.data == "buy_acc")
def buy_start(call):
    bot.send_message(call.message.chat.id, "လက်ရှိတွင် အကောင့်များ စာရင်းပြင်ဆင်နေဆဲ ဖြစ်ပါသည်။")

if __name__ == '__main__':
    print("Bot is running...")
    bot.infinity_polling()