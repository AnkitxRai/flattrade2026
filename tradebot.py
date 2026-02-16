import requests
import time
import json
from datetime import datetime
from NorenWebApi import NorenWebApi
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes



# -----------------------------
# 🔐 BROKER CREDENTIALS
# -----------------------------
userid = "FZ19246"
password = "##"
totp_secret = "35LY6332V5YJ36F5RATW36GJ7J446L43"
app_key = "9e5e9c7220b524ea19a7e6029f5140c423daea49318b23b3b36416549673bac2"


# -----------------------------
# 🤖 TELEGRAM BOT TOKEN
# -----------------------------
BOT_TOKEN = "8331147432:AAGSG4mI8d87sWEBsY0qtarAtwWbpa4viq0"

# -----------------------------
# 🤖 OPTION DETAIL
# -----------------------------
OPTION_EXPIRY = None # "28OCT25"
QTY = None

api = None


def refresh_vwap_file_config():

    global OPTION_EXPIRY, QTY
    json_url = "https://www.jsonkeeper.com/b/EDZIR"

    try:
        resp = requests.get(json_url, timeout=10)
        data = resp.json()
        if not isinstance(data, dict):
            print(f"⚠️ Invalid JSON format from {json_url}: {data}")
            return None, None, None
    except Exception as e:
        print(f"❌ Config fetch failed: {e}")
        return None, None, None

    OPTION_EXPIRY = data.get("OPTION_EXPIRY")
    QTY = data.get("QTY")
    return OPTION_EXPIRY, QTY

# -----------------------------
# 🔑 LOGIN FUNCTION
# -----------------------------
def broker_login():
    global api
    api = NorenWebApi()

    try:
        login = api.login(
            userid=userid,
            password=password,
            totp_secret=totp_secret,
            app_key=app_key
        )
        print("✅ Broker Login Successful")
        return True

    except Exception as e:
        print("❌ Login Failed:", str(e))
        return False


# -----------------------------
# 💰 CHECK TOTAL PNL
# -----------------------------
def check_pnl():
    try:
        position_book = api.get_positions() or []
    except Exception as e:
        print("Error fetching positions:", e)
        return 0.0

    if not position_book or isinstance(position_book, dict):
        return 0.0

    total_pnl = 0.0

    for pos in position_book:
        try:
            pnl_str = pos.get("rpnl", "0").replace(",", "")
            total_pnl += float(pnl_str)
        except (ValueError, TypeError):
            continue

    return round(total_pnl, 2)


# -----------------------------
# 📌 GET RUNNING POSITIONS
# -----------------------------
def get_running_positions():
    try:
        position_book = api.get_positions() or []
    except Exception:
        return []

    running = []

    for pos in position_book:
        try:
            netqty = int(pos.get("netqty", "0"))
            if netqty == 0:
                continue

            symbol = pos.get("tsym", "")
            pnl = float(pos.get("rpnl", "0").replace(",", ""))
            running.append((symbol, pnl))

        except Exception:
            continue

    return running


# -----------------------------
# 📊 BUILD STATUS MESSAGE
# -----------------------------
def build_status():
    total_pnl = check_pnl()
    running_positions = get_running_positions()
    now = datetime.now().strftime("%H:%M:%S")

    # Total pnl color
    if total_pnl > 0:
        pnl_text = f"🟢 ₹{total_pnl}"
    elif total_pnl < 0:
        pnl_text = f"🔴 ₹{total_pnl}"
    else:
        pnl_text = f"₹{total_pnl}"

    message = f"📊 Total PnL : {pnl_text}\n\n"
    message += "📌 Running Positions :\n"

    if running_positions:
        for i, (sym, pnl) in enumerate(running_positions, start=1):

            if pnl > 0:
                pnl_display = f"🟢 ₹{pnl}"
            elif pnl < 0:
                pnl_display = f"🔴 ₹{pnl}"
            else:
                pnl_display = f"₹{pnl}"

            message += f"{i}. {sym} → {pnl_display}\n"
    else:
        message += "No Running Positions\n"

    message += f"\n⏰ Last Update : {now}"

    return message


def get_atm_spot(strike_step: int = 50):
    spot = api.get_quotes("NSE", "26000")
    if spot.get("stat") != "Ok":
        raise Exception("Failed to fetch NIFTY spot:", spot)

    ltp = float(spot["lp"])
    atm_strike = round(ltp / strike_step) * strike_step
    return ltp, atm_strike


def get_atm_option(expiry, isCallOrPut: str = "C"):
    try:
        ltp, atm = get_atm_spot()
    except Exception as e:
        print("❌ get_atm_option failed:", e)
        return None
    option_type = "C" if isCallOrPut.upper() == "C" else "P"
    option_symbol = f"NIFTY{expiry}{option_type}{atm}"
    return option_symbol


def place_atm_order(expiry, callOrPut: str = "C", qty=65, offset=2):
    option_strike = get_atm_option(expiry, callOrPut)  # should return e.g., "NIFTY28OCT25C55200"

    if not option_strike:
        print("Failed to get ATM option symbol")
        return

    resp = api.place_order(
        buy_or_sell="B",
        product_type="I",
        exchange="NFO",
        tradingsymbol=option_strike,
        quantity=qty,
        price_type="MKT",
        price=0.0
    )

    if resp and resp.get("stat") == "Ok":
        print(f"✅ [ATM Order Placed] {option_strike}, Order No: {resp.get('norenordno', 'N/A')}")
    else:
        print(f"❌ [ATM Order Failed] {option_strike}, Error: {resp.get('emsg', 'Unknown error')}")

# -----------------------------
# 📈 PLACEHOLDER TRADE FUNCTIONS
# -----------------------------
def ce():
    global OPTION_EXPIRY, QTY
    refresh_vwap_file_config()

    close_all()
    place_atm_order(OPTION_EXPIRY, "C", QTY)
    print("CE Order Triggered")


def pe():
    global OPTION_EXPIRY, QTY
    refresh_vwap_file_config()

    close_all()
    place_atm_order(OPTION_EXPIRY, "P", QTY)
    print("PE Order Triggered")

def close_all():
    positions = api.get_positions() or []

    if isinstance(positions, dict) or not positions:
        print("⚠️ No valid positions found or API returned error.")
        return

    for pos in positions:
        if pos.get("stat") != "Ok":
            continue

        tsym = pos["tsym"]
        netqty = int(pos["netqty"])
        prd = pos.get("prd", "")

        # ✅ Only close intraday positions
        if prd != "I":
            continue

        if netqty > 0:  # LONG → SELL

            resp = api.place_order(
                buy_or_sell="S",
                product_type="I",
                exchange="NFO",
                tradingsymbol=tsym,
                quantity=netqty,
                price_type="MKT",
                price=0.0
            )

            if resp is None or resp.get("stat") != "Ok":
                print(f"[Error] Failed to close LONG {tsym}: {resp}")
            else:
                print(f"Closing LONG {tsym}: {resp.get('norenordno', 'Reverse Order Placed')}")

        elif netqty < 0:  # SHORT → BUY

            resp = api.place_order(
                buy_or_sell="B",
                product_type="I",
                exchange="NFO",
                tradingsymbol=tsym,
                quantity=netqty,
                price_type="MKT",
                price=0.0
            )

            if resp is None or resp.get("stat") != "Ok":
                print(f"[Error] Failed to close SHORT {tsym}: {resp}")
            else:
                print(f"Closing SHORT {tsym}: {resp.get('norenordno', 'Reverse Order Placed')}")


# -----------------------------
# ⌨ KEYBOARD
# -----------------------------
def main_keyboard():
    keyboard = [
        ["CE", "PE"],
        ["Close"],
        ["Check PnL"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# -----------------------------
# 🚀 START COMMAND
# -----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        build_status(),
        reply_markup=main_keyboard()
    )


# -----------------------------
# 🎯 BUTTON HANDLER
# -----------------------------
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "CE":
        ce()

    elif text == "PE":
        pe()

    elif text == "Close":
        close_all()

    elif text == "Check PnL":
        pass

    await update.message.reply_text(
        build_status(),
        reply_markup=main_keyboard()
    )


# -----------------------------
# 🏁 MAIN
# -----------------------------
def main():

    if not broker_login():
        print("Stopping bot due to login failure")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))

    print("🤖 Bot Running...")
    app.run_polling()


if __name__ == "__main__":
    main()
