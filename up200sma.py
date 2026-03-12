import requests
import time
from datetime import datetime, timedelta
from NorenWebApi import NorenWebApi


################################ cred ############################

userid = "FZ19246"
password = "##"
totp_secret = "35LY6332V5YJ36F5RATW36GJ7J446L43"
app_key = "9e5e9c7220b524ea19a7e6029f5140c423daea49318b23b3b36416549673bac2"

# userid = "FZ31096"
# password = "##"
# totp_secret = "V3B3T3AZ3U6236HO35BQRL6S4KP725O5"
# app_key = "271b7fc4385a31a3855553a29e31af8a1ee91232f3f980aa810197afe58c8ff9"


############################## config ###########################

SENSIBUL_FUTURE_EXPIRY = None
OPTION_EXPIRY          = None
QTY                    = None
TRADING_ACTIVE         = False
FIRST_TRADE            = True
ACTIVE_POSITION        = None
ENTRY_STRIKE           = None
TELEGRAM               = True


# ─────────────────────────────────────────────
# Fetch Strike OI and VWAP Data
# ─────────────────────────────────────────────
def fetch_nt_total():
    url     = "https://webapi.niftytrader.in/webapi/option/option-chain-data?symbol=nifty&exchange=nse&expiryDate=&atmBelow=2&atmAbove=2"
    headers = {"User-Agent": "Mozilla/5.0", "accept": "application/json"}
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        data = resp.json()
        if not data or not isinstance(data, dict):
            print(f"❌ NT bad response"); return None
        return data
    except Exception as e:
        print(f"❌ NT fetch error: {e}"); return None

# ─────────────────────────────────────────────
# Fetch option expiry list
# ─────────────────────────────────────────────
def fetch_nt_expiry():
    created_time = (datetime.now() - timedelta(minutes=2)).strftime("%H:%M:%S")
    url     = f"https://webapi.niftytrader.in/webapi/Option/option-chain-calculator-data?symbol=nifty&expiryDate=&createdTime={created_time}&isloader=false&atmBelow=2&atmAbove=2"
    headers = {"User-Agent": "Mozilla/5.0", "accept": "application/json"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        if not data or not isinstance(data, dict):
            print(f"❌ NT expiry bad response"); return None
        return data  # ← missing
    except Exception as e:
        print(f"❌ NT expiry fetch error: {e}"); return None

# ─────────────────────────────────────────────
# Set current expiry and next expiry based on date
# ─────────────────────────────────────────────
def get_auto_expiry():
    data = fetch_nt_expiry()
    if not data:
        return None
    try:
        dates   = data["resultData"]["opExpiryDates"]
        today   = datetime.now().date()

        def trading_days(from_date, to_date):
            count = 0
            d = from_date
            while d <= to_date:
                if d.weekday() < 5:  # Mon–Fri
                    count += 1
                d += timedelta(days=1)
            return count

        def to_expiry_fmt(iso_str):
            dt = datetime.fromisoformat(iso_str)
            return dt.strftime("%d%b%y").upper()  # "17MAR26"

        current_expiry = datetime.fromisoformat(dates[0]).date()
        days_left      = trading_days(today, current_expiry)

        if days_left <= 2:
            chosen = dates[1]
            print(f"⏭️ Expiry shift — only {days_left} trading days left, using next: {dates[1]}")
        else:
            chosen = dates[0]
            print(f"📅 Expiry: {chosen} | {days_left} trading days left")

        return to_expiry_fmt(chosen)

    except Exception as e:
        print(f"❌ get_auto_expiry error: {e}")
        return None


def refresh_config():
    global SENSIBUL_FUTURE_EXPIRY, OPTION_EXPIRY, QTY, TRADING_ACTIVE
    json_url = "https://www.jsonkeeper.com/b/EDZIR"
    try:
        resp = requests.get(json_url, timeout=10)
        data = resp.json()
        if not isinstance(data, dict):
            print(f"⚠️ Invalid config format"); return
    except Exception as e:
        print(f"❌ Config fetch failed: {e}"); return
    SENSIBUL_FUTURE_EXPIRY = data.get("SENSIBUL_FUTURE_EXPIRY")
    # OPTION_EXPIRY          = data.get("OPTION_EXPIRY") # Setting auto expiry in main
    QTY                    = data.get("QTY")
    TRADING_ACTIVE         = data.get("TRADING_ACTIVE", False)


# ─────────────────────────────────────────────
# FETCH CANDLES — 1 week back → today
# Returns ts, ltp, signal (1=bull, -1=bear, 0=no cross)
# ─────────────────────────────────────────────
def fetch_candles():
    today    = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    url     = "https://oxide.sensibull.com/v1/compute/candles/NIFTY"
    payload = {
        "from_date":    week_ago,
        "to_date":      today,
        "interval":     "1M",
        "skip_last_ts": True,
    }

    try:
        resp    = requests.post(url, json=payload, timeout=15)
        candles = resp.json()["payload"]["candles"]
        if not candles:
            return None, None, None

        latest = candles[-1]
        ts     = latest["ts"]
        ltp    = latest["close"]

        if len(candles) < 201:
            print(f"⚠️ Only {len(candles)} candles — need 201 for SMA200")
            return ts, ltp, None

        closes = [c["close"] for c in candles]

        sma5_now    = sum(closes[-5:])     / 5
        sma5_prev   = sum(closes[-6:-1])   / 5
        sma200_now  = sum(closes[-200:])   / 200
        sma200_prev = sum(closes[-201:-1]) / 200

        cross_up   = sma5_prev <= sma200_prev and sma5_now > sma200_now
        cross_down = sma5_prev >= sma200_prev and sma5_now < sma200_now
        bull_side  = sma5_now > sma200_now
        bear_side  = sma5_now < sma200_now

        return ts, ltp, {
            "sma5"       : round(sma5_now,   2),
            "sma200"     : round(sma200_now, 2),
            "cross_up"   : cross_up,
            "cross_down" : cross_down,
            "bull_side"  : bull_side,
            "bear_side"  : bear_side,
        }

    except Exception as e:
        print(f"❌ fetch_candles error: {e}")
        return None, None, None


def get_atm_strike(index):
    return round(index / 50) * 50


def get_adx():
    today    = datetime.now().strftime("%Y-%m-%d")
    url      = "https://oxide.sensibull.com/v1/compute/candles/NIFTY"
    payload  = {
        "from_date":    today,
        "to_date":      today,
        "interval":     "1M",
        "skip_last_ts": True,
    }
    try:
        data  = requests.post(url, json=payload, timeout=15).json()
        c     = data["payload"]["candles"]
        high  = [x["high"]  for x in c]
        low   = [x["low"]   for x in c]
        close = [x["close"] for x in c]

        tr, plus_dm, minus_dm = [], [], []
        for i in range(1, len(c)):
            tr.append(max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1])))
            up = high[i] - high[i-1]
            dn = low[i-1] - low[i]
            plus_dm.append(up if up > dn and up > 0 else 0)
            minus_dm.append(dn if dn > up and dn > 0 else 0)

        def rma(x, p):
            s = sum(x[:p]) / p
            out = [s]
            for v in x[p:]:
                s = (s * (p-1) + v) / p
                out.append(s)
            return out

        p    = 14
        tr_r = rma(tr, p)
        pdi  = [(a/b)*100 for a, b in zip(rma(plus_dm, p), tr_r)]
        mdi  = [(a/b)*100 for a, b in zip(rma(minus_dm, p), tr_r)]
        dx   = [abs(a-b)/(a+b)*100 if (a+b) != 0 else 0 for a, b in zip(pdi, mdi)]
        return round(rma(dx, p)[-1], 1)

    except Exception as e:
        print(f"❌ ADX error: {e}")
        return None

def get_day_change():
    url     = "https://webapi.niftytrader.in/webapi/symbol/today-spot-data?symbol=nifty&created_at="
    headers = {"User-Agent": "Mozilla/5.0", "accept": "application/json"}
    try:
        data    = requests.get(url, headers=headers).json()
        index   = data["resultData"]["last_trade_price"]
        change  = data["resultData"]["change_value"]
        rounded = round(index / 50) * 50
        return index, change, rounded
    except Exception as e:
        print(f"❌ Change fetch error: {e}"); return None


def option_vwap(locked_strike=None):
    result = get_day_change()
    if result is None:
        return None
    index, change, rounded = result

    option_chain = fetch_nt_total()
    if not option_chain:
        return None

    try:
        totals  = option_chain["resultData"]["opTotals"]["total_calls_puts"]
        coi_pcr = totals["total_puts_change_oi"] - totals["total_calls_change_oi"]

        round_value = locked_strike if locked_strike is not None else (rounded - 50 if coi_pcr > 0 else rounded + 50)

        data_list = option_chain["resultData"]["opDatas"]
        match     = next((item for item in data_list if item["strike_price"] == round_value), None)
        if not match:
            print("⚠️ No matching strike:", round_value); return None

        return (
            index, change, round_value, coi_pcr,
            match.get("calls_ltp"),          match.get("calls_average_price"),
            match.get("puts_ltp"),           match.get("puts_average_price"),
        )
    except Exception as e:
        print("❌ option_vwap error:", e); return None


def send_telegram_message(msg, imp=True):
    if not TELEGRAM:
        return
    BOT_TOKEN      = "8331147432:AAGSG4mI8d87sWEBsY0qtarAtwWbpa4viq0"
    CHANNEL_ID     = "-1003494200670"
    CHANNEL_ID_IMP = "-1003448158591"
    chat_id        = CHANNEL_ID_IMP if imp else CHANNEL_ID
    url            = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=15)
    except Exception as e:
        print("❌ Telegram error:", e)


def format_output(ts, ltp, coi_pcr, change_pts, ma_data, adx):
    time_str     = datetime.fromisoformat(ts).strftime("%H:%M")
    adx_str = f"ADX:{adx}" if adx else "ADX:--"
    coi_flag     = "🟢" if coi_pcr > 0 else "🔴"
    coi_pcr_k    = round(coi_pcr / 1000, 1)
    change_emoji = "🟢" if change_pts >= 0 else "🔴"

    if ma_data:
        cross_str = "🟢" if ma_data["bull_side"] else "🔴"
        ma_str    = f"SMA5:{ma_data['sma5']} SMA200:{ma_data['sma200']}"
    else:
        cross_str = "⏳"
        ma_str    = "SMA warming up"

    print(f"🕒 {time_str} | {ltp} | {change_pts} {change_emoji} | MA:{cross_str} | {adx_str} | {coi_pcr_k}K{coi_flag} | {ma_str}")
    send_telegram_message(f"🕒{time_str} | {change_pts} {change_emoji} | MA:{cross_str} | {adx_str} | {coi_pcr_k}K{coi_flag}", False)

def calculate_realized_pnl():
    position_book = api.get_positions() or []
    if not position_book or isinstance(position_book, dict):
        return 0.0
    total_pnl = 0.0
    for pos in position_book:
        try:
            total_pnl += float(pos.get("rpnl", "0").replace(",", ""))
        except (ValueError, TypeError):
            continue
    return total_pnl


def cancel_all_pending_mis_orders():
    orders = api.get_order_book() or []
    if isinstance(orders, dict) or not orders:
        return
    for order in orders:
        try:
            if order.get("status") == "OPEN" and order.get("s_prdt_ali") == "MIS":
                order_no = order.get("norenordno")
                if order_no:
                    resp = api.cancel_order(order_no)
                    if resp.get("stat") == "Ok":
                        print(f"Canceled order {order_no}")
        except Exception as e:
            print(f"Exception canceling order: {e}")


def close_all_positions():
    positions = api.get_positions() or []
    if isinstance(positions, dict) or not positions:
        return
    for pos in positions:
        if pos.get("stat") != "Ok": continue
        netqty = int(pos["netqty"])
        if pos.get("prd") != "I" or netqty == 0: continue
        side = "S" if netqty > 0 else "B"
        resp = api.place_order(
            buy_or_sell=side, product_type="I", exchange="NFO",
            tradingsymbol=pos["tsym"], quantity=abs(netqty),
            price_type="MKT", price=0.0
        )
        if resp is None or resp.get("stat") != "Ok":
            print(f"[Error] Failed to close {pos['tsym']}: {resp}")
        else:
            print(f"Closing {pos['tsym']}: {resp.get('norenordno')}")


def before_execution():
    try:
        pnl = calculate_realized_pnl()
        print(f"Realized PNL: {pnl}")
    except Exception as e:
        print(f"Error calculating PNL: {e}"); return False
    if pnl < -4000:
        print("⚠️ Loss exceeds -4000, skipping trade."); return False
    cancel_all_pending_mis_orders()
    close_all_positions()
    return True


def place_atm_order(expiry, callOrPut="C", qty=65, atm=None):
    option_strike = f"NIFTY{expiry}{callOrPut.upper()}{atm}"
    resp = api.place_order(
        buy_or_sell="B", product_type="I", exchange="NFO",
        tradingsymbol=option_strike, quantity=qty,
        price_type="MKT", price=0.0
    )
    if resp and resp.get("stat") == "Ok":
        print(f"✅ Order placed: {option_strike} | {resp.get('norenordno')}")
    else:
        print(f"❌ Order failed: {option_strike} | {resp.get('emsg', 'Unknown')}")
    return resp


def execute_call_trade(atm):
    global ACTIVE_POSITION, ENTRY_STRIKE
    if not before_execution(): return
    place_atm_order(OPTION_EXPIRY, "C", QTY, atm)
    ACTIVE_POSITION = "CALL"
    ENTRY_STRIKE    = atm
    send_telegram_message(f"🟢 Entered Call | Strike {atm}")
    print(f"🟢 Entered Call | Strike {atm}")


def execute_put_trade(atm):
    global ACTIVE_POSITION, ENTRY_STRIKE
    if not before_execution(): return
    place_atm_order(OPTION_EXPIRY, "P", QTY, atm)
    ACTIVE_POSITION = "PUT"
    ENTRY_STRIKE    = atm
    send_telegram_message(f"🔴 Entered Put | Strike {atm}")
    print(f"🔴 Entered Put | Strike {atm}")


def close_trade():
    global ACTIVE_POSITION, ENTRY_STRIKE
    cancel_all_pending_mis_orders()
    close_all_positions()
    ACTIVE_POSITION = None
    ENTRY_STRIKE    = None
    send_telegram_message("❌ Closing all positions")
    print("❌ Closing all positions")


def auto_close_eod():
    now = datetime.now()
    if now.hour == 15 and now.minute >= 12:
        if ACTIVE_POSITION is not None:
            print("⏰ 3:12 PM — Auto closing.")
            close_trade()
        return True
    return False


def monitor_loop():
    global ACTIVE_POSITION, FIRST_TRADE

    if auto_close_eod():
        return

    ts, ltp, ma_data = fetch_candles()
    if ts is None or ltp is None:
        print(f"{datetime.now().strftime('%H:%M')} | Candle fetch error, skipping…")
        return

    result = option_vwap(locked_strike=ENTRY_STRIKE)
    if result is None:
        print(f"{datetime.now().strftime('%H:%M')} | option_vwap error, skipping…")
        return
    index, change, round_value, coi_pcr, cltp, cvwap, pltp, pvwap = result

    atm = get_atm_strike(index)
    adx = get_adx()

    format_output(ts, ltp, coi_pcr, change, ma_data, adx)

    if ma_data is None:
        print(f"{datetime.now().strftime('%H:%M')} | SMA200 warming up, skipping…")
        return

    if FIRST_TRADE and ACTIVE_POSITION is None:
        FIRST_TRADE = False
        print("ℹ️ First candle — skipping trade.")
        return

    # ── Entry / Exit conditions ──
    # MA cross + option VWAP only
    call_entry = ma_data["bull_side"] and cltp > cvwap
    put_entry  = ma_data["bear_side"] and pltp > pvwap

    # ── CALL logic ──
    if ACTIVE_POSITION == "CALL":
        if not call_entry:
            close_trade()
    elif ACTIVE_POSITION is None:
        if call_entry:
            execute_call_trade(atm)

    # ── PUT logic ──
    if ACTIVE_POSITION == "PUT":
        if not put_entry:
            close_trade()
    elif ACTIVE_POSITION is None:
        if put_entry:
            execute_put_trade(atm)


if __name__ == "__main__":
    api = NorenWebApi()
    try:
        login = api.login(userid=userid, password=password, totp_secret=totp_secret, app_key=app_key)
    except Exception as e:
        print("Login Failed:", str(e))
        send_telegram_message(f"❌ Login Error: {str(e)}")

    auto_expiry = get_auto_expiry()
    if auto_expiry:
        OPTION_EXPIRY = auto_expiry

    while True:
        try:
            refresh_config()

            if not TRADING_ACTIVE:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Trading inactive. Sleeping 60s…")
                time.sleep(60)
                continue

            try:
                monitor_loop()
            except Exception as e:
                print(f"❌ Monitor error: {e}")

            now = datetime.now()
            time.sleep(60 - now.second + 5)

        except KeyboardInterrupt:
            print("🛑 Stopped by user.")
            break
        except Exception as e:
            print(f"🔥 FATAL: {e}")
            time.sleep(30)