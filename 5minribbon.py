import requests
import time
from datetime import datetime
from NorenWebApi import NorenWebApi

######## Logic : Color change ribbon is based on 5 min, but check exit 30 point condition on every 1 min
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
OPTION_EXPIRY = None
QTY = None
TRADING_ACTIVE = False
FIRST_TRADE = True
ACTIVE_POSITION = None
ENTRY_STRIKE = None
ENTRY_NIFTY_PRICE = None       # ← for 30pt SL
PREV_ADX = 0
LAT_ADX = 0
TELEGRAM = False
SL_POINTS = 30                 # ← NIFTY point SL distance


def refresh_vwap_file_config():
    global SENSIBUL_FUTURE_EXPIRY, OPTION_EXPIRY, QTY, TRADING_ACTIVE
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

    SENSIBUL_FUTURE_EXPIRY = data.get("SENSIBUL_FUTURE_EXPIRY")
    OPTION_EXPIRY = data.get("OPTION_EXPIRY")
    QTY = data.get("QTY")
    TRADING_ACTIVE = data.get("TRADING_ACTIVE", False)
    return SENSIBUL_FUTURE_EXPIRY, OPTION_EXPIRY, QTY, TRADING_ACTIVE


# ─────────────────────────────────────────────
# T3 RIBBON — 5M candles
# returns 1 = green, -1 = red, 0 = grey
# ─────────────────────────────────────────────
def _ema(src, length):
    k, out = 2.0 / (length + 1), []
    e = src[0]
    for i, v in enumerate(src):
        e = v if i == 0 else v * k + e * (1 - k)
        out.append(e)
    return out


def _t3(src, length, smooth=0.30):
    e1 = _ema(src, length)
    e2 = _ema(e1,  length)
    e3 = _ema(e2,  length)
    e4 = _ema(e3,  length)
    e5 = _ema(e4,  length)
    e6 = _ema(e5,  length)
    f  = smooth
    c1 = -(f**3)
    c2 = 3*f**2 + 3*f**3
    c3 = -6*f**2 - 3*f - 3*f**3
    c4 = 1 + 3*f + f**3 + 3*f**2
    return [c1*e6[j] + c2*e5[j] + c3*e4[j] + c4*e3[j] for j in range(len(src))]


def fetch_candles_1m():
    """Fetch 1M candles — returns ts and ltp (spot price) only"""
    today = datetime.now().strftime("%Y-%m-%d")
    url = "https://oxide.sensibull.com/v1/compute/candles/NIFTY"
    payload = {
        "from_date":    today,
        "to_date":      today,
        "interval":     "1M",
        "skip_last_ts": True,
    }
    try:
        candles = requests.post(url, json=payload).json()["payload"]["candles"]
        if not candles:
            return None, None
        latest = candles[-1]
        return latest["ts"], latest["close"]
    except Exception as e:
        print(f"❌ fetch_candles_1m error: {e}")
        return None, None


def fetch_ribbon_5m():
    """Fetch 5M candles — compute T3 ribbon, return ribbon trend"""
    today = datetime.now().strftime("%Y-%m-%d")
    url = "https://oxide.sensibull.com/v1/compute/candles/NIFTY"
    payload = {
        "from_date":    today,
        "to_date":      today,
        "interval":     "5M",
        "skip_last_ts": True,
    }
    try:
        candles = requests.post(url, json=payload).json()["payload"]["candles"]
        if not candles or len(candles) < 20:
            return None

        hlc3 = [(c["high"] + c["low"] + c["close"]) / 3.0 for c in candles]

        w1 = _t3(hlc3, 9)
        w2 = _t3(hlc3, 10)
        w3 = _t3(hlc3, 11)
        w4 = _t3(hlc3, 12)

        i      = len(candles) - 1
        fast   = (w1[i] + w2[i]) / 2.0
        slow   = (w3[i] + w4[i]) / 2.0
        center = (w1[i] + w2[i] + w3[i] + w4[i]) / 4.0
        prev_c = (w1[i-1] + w2[i-1] + w3[i-1] + w4[i-1]) / 4.0

        if   fast > slow and center > prev_c: return 1    # green
        elif fast < slow and center < prev_c: return -1   # red
        else:                                 return 0    # grey

    except Exception as e:
        print(f"❌ fetch_ribbon_5m error: {e}")
        return None


def get_atm_strike(index):
    return round(index / 50) * 50


def get_adx():
    if not SENSIBUL_FUTURE_EXPIRY:
        print("❗ SENSIBUL_FUTURE_EXPIRY not configured.")
        return None

    today = datetime.now().strftime("%Y-%m-%d")
    url = f"https://oxide.sensibull.com/v1/compute/candles/{SENSIBUL_FUTURE_EXPIRY}"
    payload = {
        "from_date":    today,
        "to_date":      today,
        "interval":     "5M",       # ADX also on 5M to match ribbon
        "skip_last_ts": True,
    }

    try:
        data = requests.post(url, json=payload).json()
        c = data["payload"]["candles"]

        high  = [x["high"]  for x in c]
        low   = [x["low"]   for x in c]
        close = [x["close"] for x in c]

        tr, plus_dm, minus_dm = [], [], []
        for i in range(1, len(c)):
            tr.append(max(high[i]-low[i],
                          abs(high[i]-close[i-1]),
                          abs(low[i]-close[i-1])))
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

        p = 14
        tr_r = rma(tr, p)
        pdi  = [(a/b)*100 for a, b in zip(rma(plus_dm, p), tr_r)]
        mdi  = [(a/b)*100 for a, b in zip(rma(minus_dm, p), tr_r)]
        dx   = [abs(a-b)/(a+b)*100 if (a+b) != 0 else 0 for a, b in zip(pdi, mdi)]

        return round(rma(dx, p)[-1], 1)

    except Exception as e:
        print(f"❌ ADX error: {e}")
        return None


def fetch_nt_total():
    url = "https://webapi.niftytrader.in/webapi/option/option-chain-data?symbol=nifty&exchange=nse&expiryDate=&atmBelow=2&atmAbove=2"
    headers = {"User-Agent": "Mozilla/5.0", "accept": "application/json"}
    try:
        return requests.get(url, headers=headers).json()
    except Exception as e:
        print(f"❌ NT fetch error: {e}")
        return None


def get_day_change():
    url = "https://webapi.niftytrader.in/webapi/symbol/today-spot-data?symbol=nifty&created_at="
    headers = {"User-Agent": "Mozilla/5.0", "accept": "application/json"}
    try:
        data = requests.get(url, headers=headers).json()
        index   = data["resultData"]["last_trade_price"]
        change  = data["resultData"]["change_value"]
        rounded = round(index / 50) * 50
        return index, change, rounded
    except Exception as e:
        print(f"❌ Change fetch error: {e}")
        return None


def option_vwap(locked_strike=None):
    result = get_day_change()
    if result is None:
        print("❌ get_day_change failed")
        return None
    index, change, rounded = result

    option_chain = fetch_nt_total()
    if not option_chain:
        print("❌ No option chain data")
        return None

    try:
        totals  = option_chain["resultData"]["opTotals"]["total_calls_puts"]
        coi_pcr = totals["total_puts_change_oi"] - totals["total_calls_change_oi"]

        if locked_strike is not None:
            round_value = locked_strike
        else:
            round_value = rounded - 50 if coi_pcr > 0 else rounded + 50

        data_list = option_chain["resultData"]["opDatas"]
        match = next((item for item in data_list if item["strike_price"] == round_value), None)

        if not match:
            print("⚠️ No matching strike:", round_value)
            return None

        cltp  = match.get("calls_ltp")
        cvwap = match.get("calls_average_price")
        pltp  = match.get("puts_ltp")
        pvwap = match.get("puts_average_price")

        return (index, change, round_value, coi_pcr, cltp, cvwap, pltp, pvwap)

    except Exception as e:
        print("❌ Error searching data:", e)
        return None


def send_telegram_message(msg, imp=True):
    if not TELEGRAM:
        return
    BOT_TOKEN      = "8331147432:AAGSG4mI8d87sWEBsY0qtarAtwWbpa4viq0"
    CHANNEL_ID     = "-1003494200670"
    CHANNEL_ID_IMP = "-1003448158591"
    chat_id = CHANNEL_ID_IMP if imp else CHANNEL_ID
    url  = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": msg}
    try:
        requests.post(url, data=data, timeout=5)
    except Exception as e:
        print("❌ send_telegram_message error:", e)


def format_output(ts, ltp, coi_pcr, change_pts, adx, ribbon):
    time_str     = datetime.fromisoformat(ts).strftime("%H:%M")
    coi_flag     = "🟢" if coi_pcr > 0 else "🔴"
    coi_pcr_k    = round(coi_pcr / 1000, 1)
    change_emoji = "🟢" if change_pts >= 0 else "🔴"

    if ribbon == 1:    rib_flag = "🟢RIB"
    elif ribbon == -1: rib_flag = "🔴RIB"
    else:              rib_flag = "🟡RIB"

    print(f"🕒 {time_str} | {ltp} | {change_pts} {change_emoji} | ADX:{adx} | {rib_flag} | {coi_pcr_k}K{coi_flag}")
    send_telegram_message(f"🕒{time_str} | {change_pts} {change_emoji} | ADX:{adx} | {rib_flag} | {coi_pcr_k}K{coi_flag}", False)


def calculate_realized_pnl():
    position_book = api.get_positions() or []
    if not position_book or isinstance(position_book, dict):
        print("⚠️ No valid positions found or API returned error. Returning PnL = 0.")
        return 0.0
    total_pnl = 0.0
    for pos in position_book:
        try:
            pnl_str = pos.get("rpnl", "0").replace(",", "")
            total_pnl += float(pnl_str)
        except (ValueError, TypeError):
            continue
    return total_pnl


def cancel_all_pending_mis_orders():
    orders = api.get_order_book() or []
    if isinstance(orders, dict) or not orders:
        print("ℹ️ No active orders found or API returned an invalid response.")
        return
    canceled_count = 0
    for order in orders:
        try:
            if order.get("status") == "OPEN" and order.get("s_prdt_ali") == "MIS":
                order_no = order.get("norenordno")
                if order_no:
                    resp = api.cancel_order(order_no)
                    if resp.get("stat") == "Ok":
                        canceled_count += 1
                        print(f"Canceled order {order_no} successfully.")
                    else:
                        print(f"Failed to cancel order {order_no}: {resp.get('emsg')}")
        except Exception as e:
            print(f"Exception while canceling order {order.get('norenordno')}: {str(e)}")
    print(f"Total canceled MIS orders: {canceled_count}")


def close_all_positions():
    positions = api.get_positions() or []
    if isinstance(positions, dict) or not positions:
        print("⚠️ No valid positions found or API returned error.")
        return
    for pos in positions:
        if pos.get("stat") != "Ok":
            continue
        tsym   = pos["tsym"]
        netqty = int(pos["netqty"])
        prd    = pos.get("prd", "")
        if prd != "I":
            continue
        if netqty == 0:
            continue
        side = "S" if netqty > 0 else "B"
        resp = api.place_order(
            buy_or_sell=side,
            product_type="I",
            exchange="NFO",
            tradingsymbol=tsym,
            quantity=abs(netqty),
            price_type="MKT",
            price=0.0
        )
        if resp is None or resp.get("stat") != "Ok":
            print(f"[Error] Failed to close {tsym}: {resp}")
        else:
            print(f"Closing {tsym}: {resp.get('norenordno', 'Order Placed')}")


def before_execution():
    try:
        pnl = calculate_realized_pnl()
        print(f"Realized PNL: {pnl}")
    except Exception as e:
        print(f"Error calculating PNL: {e}")
        return False

    if pnl < -4000:
        print("⚠️ Loss exceeds -4000, skipping trade execution.")
        return False

    cancel_all_pending_mis_orders()
    close_all_positions()
    return True


def place_atm_order(expiry, callOrPut: str = "C", qty=65, atm=None):
    option_strike = f"NIFTY{expiry}{callOrPut.upper()}{atm}"
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
    return resp


def execute_call_trade(ATM, strike, nifty_price):
    global ACTIVE_POSITION, QTY, ENTRY_STRIKE, ENTRY_NIFTY_PRICE
    if not before_execution():
        return
    place_atm_order(OPTION_EXPIRY, "C", QTY, ATM)
    ACTIVE_POSITION    = 'CALL'
    ENTRY_STRIKE       = strike
    ENTRY_NIFTY_PRICE  = nifty_price      # ← lock NIFTY price for SL
    send_telegram_message(f"🟢 Entered Call | Strike {strike} | NIFTY {nifty_price}")
    print(f"🟢 Entered Call | Strike {strike} | NIFTY {nifty_price}")


def execute_put_trade(ATM, strike, nifty_price):
    global ACTIVE_POSITION, QTY, ENTRY_STRIKE, ENTRY_NIFTY_PRICE
    if not before_execution():
        return
    place_atm_order(OPTION_EXPIRY, "P", QTY, ATM)
    ACTIVE_POSITION    = 'PUT'
    ENTRY_STRIKE       = strike
    ENTRY_NIFTY_PRICE  = nifty_price      # ← lock NIFTY price for SL
    send_telegram_message(f"🔴 Entered Put | Strike {strike} | NIFTY {nifty_price}")
    print(f"🔴 Entered Put | Strike {strike} | NIFTY {nifty_price}")


def close_trade(reason=""):
    global ACTIVE_POSITION, ENTRY_STRIKE, ENTRY_NIFTY_PRICE
    cancel_all_pending_mis_orders()
    close_all_positions()
    ACTIVE_POSITION   = None
    ENTRY_STRIKE      = None
    ENTRY_NIFTY_PRICE = None              # ← reset SL reference
    msg = f"❌ Closing all position{' | ' + reason if reason else ''}"
    send_telegram_message(msg)
    print(msg)


def auto_close_eod():
    """Auto close all positions at end of day 3:12 PM"""
    now = datetime.now()
    if now.hour == 15 and now.minute >= 12:
        if ACTIVE_POSITION is not None:
            print(f"⏰ 3:12 PM — Auto closing position.")
            close_trade("EOD")
        return True
    return False


def monitor_loop():
    global ACTIVE_POSITION, PREV_ADX, LAT_ADX, FIRST_TRADE

    if auto_close_eod():
        return

    # 1M fetch — for LTP (real-time price) and display
    ts, ltp = fetch_candles_1m()
    if ts is None or ltp is None:
        print(f"{datetime.now().strftime('%H:%M')} | Candle fetch error, skipping…")
        return

    # 5M fetch — ribbon direction and ADX
    ribbon = fetch_ribbon_5m()

    result = option_vwap(locked_strike=ENTRY_STRIKE)
    if result is None:
        print(f"{datetime.now().strftime('%H:%M')} | option_vwap fetch error, skipping…")
        return
    index, change, round_value, coi_pcr, cltp, cvwap, pltp, pvwap = result

    atm = get_atm_strike(index)

    PREV_ADX = LAT_ADX
    LAT_ADX  = get_adx()

    format_output(ts, ltp, coi_pcr, change, LAT_ADX, ribbon)

    # ── NIFTY 30pt SL check — runs every minute on 1M price ──────
    if ACTIVE_POSITION is not None and ENTRY_NIFTY_PRICE is not None:
        move = ltp - ENTRY_NIFTY_PRICE
        if ACTIVE_POSITION == 'CALL' and move <= -SL_POINTS:
            print(f"🛑 SL HIT | CALL | Entry {ENTRY_NIFTY_PRICE} | Now {ltp} | Move {move:.1f}")
            send_telegram_message(f"🛑 SL HIT | CALL | Entry {ENTRY_NIFTY_PRICE} | Now {ltp}")
            close_trade("SL Hit")
            return
        elif ACTIVE_POSITION == 'PUT' and move >= SL_POINTS:
            print(f"🛑 SL HIT | PUT | Entry {ENTRY_NIFTY_PRICE} | Now {ltp} | Move {move:.1f}")
            send_telegram_message(f"🛑 SL HIT | PUT | Entry {ENTRY_NIFTY_PRICE} | Now {ltp}")
            close_trade("SL Hit")
            return

    # ── Ribbon/ADX checks (5M based) ─────────────────────────────
    if ribbon is None or LAT_ADX is None:
        print(f"{datetime.now().strftime('%H:%M')} | Indicators not ready, skipping…")
        return

    if ribbon == 0:
        if ACTIVE_POSITION is not None:
            close_trade("Ribbon Grey")
        print(f"{datetime.now().strftime('%H:%M')} | Ribbon grey — no trade.")
        return

    if FIRST_TRADE and ACTIVE_POSITION is None:
        FIRST_TRADE = False
        print("ℹ️ First candle — skipping trade.")
        return

    # ── Entry conditions (5M ribbon + 5M ADX) ────────────────────
    call_entry = ribbon == 1  and cltp > cvwap and LAT_ADX > PREV_ADX
    put_entry  = ribbon == -1 and pltp > pvwap and LAT_ADX > PREV_ADX

    # ── CALL logic ───────────────────────────────────────────────
    if ACTIVE_POSITION == 'CALL':
        if not call_entry:
            close_trade("Signal Exit")

    elif ACTIVE_POSITION is None:
        if call_entry:
            execute_call_trade(atm, round_value, ltp)   # ← pass ltp as NIFTY entry price

    # ── PUT logic ────────────────────────────────────────────────
    if ACTIVE_POSITION == 'PUT':
        if not put_entry:
            close_trade("Signal Exit")

    elif ACTIVE_POSITION is None:
        if put_entry:
            execute_put_trade(atm, round_value, ltp)    # ← pass ltp as NIFTY entry price


if __name__ == "__main__":
    api = NorenWebApi()
    try:
        login = api.login(userid=userid, password=password, totp_secret=totp_secret, app_key=app_key)
    except Exception as e:
        print("Login Failed:", str(e))
        send_telegram_message(f"❌ Login Error: {str(e)}")

    refresh_vwap_file_config()

    if not SENSIBUL_FUTURE_EXPIRY:
        print("No SENSIBUL_FUTURE_EXPIRY configured. Exiting.")
        exit(1)

    while True:
        try:
            refresh_vwap_file_config()

            if not TRADING_ACTIVE:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Trading inactive. Sleeping for 1 minute...")
                time.sleep(60)
                continue

            try:
                monitor_loop()
            except Exception as e:
                print(f"❌ Monitor error: {e}")

            now = datetime.now()
            seconds_to_next_minute = 60 - now.second
            time.sleep(seconds_to_next_minute + 5)

        except KeyboardInterrupt:
            print("🛑 Monitor stopped by user.")
            break

        except Exception as e:
            print(f"🔥 FATAL loop crash: {e}")
            time.sleep(30)