import requests
import time
from datetime import datetime
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
OPTION_EXPIRY = None
QTY = None
TRADING_ACTIVE = False
FIRST_TRADE = True
ACTIVE_POSITION = None
PREV_ADX = 0
LAT_ADX = 0
TELEGRAM = False
COI_HISTORY = []


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


def fetch_candles():
    """Fetch NIFTY spot candles — returns ts, ltp, supertrend"""
    today = datetime.now().strftime("%Y-%m-%d")
    url = "https://oxide.sensibull.com/v1/compute/candles/NIFTY"
    payload = {
        "from_date": today,
        "to_date": today,
        "interval": "1M",
        "skip_last_ts": True
    }

    try:
        candles = requests.post(url, json=payload).json()["payload"]["candles"]
        if not candles:
            return None, None, None

        latest = candles[-1]
        ts  = latest["ts"]
        ltp = latest["close"]

        period     = 10
        multiplier = 3

        if len(candles) < period + 1:
            return ts, ltp, None

        high  = [c["high"] for c in candles]
        low   = [c["low"] for c in candles]
        close = [c["close"] for c in candles]

        def rma(x, p):
            s = sum(x[:p]) / p
            out = [s]
            for v in x[p:]:
                s = (s * (p-1) + v) / p
                out.append(s)
            return out

        tr = [max(high[i] - low[i],
                  abs(high[i] - close[i-1]),
                  abs(low[i] - close[i-1])) for i in range(1, len(candles))]

        atr = rma(tr, period)

        trend      = 1
        prev_upper = prev_lower = None
        atr_start  = period

        for i in range(len(atr)):
            idx   = atr_start + i
            hl2   = (high[idx] + low[idx]) / 2
            upper = hl2 + multiplier * atr[i]
            lower = hl2 - multiplier * atr[i]

            if prev_upper is not None:
                upper = min(upper, prev_upper) if close[idx-1] < prev_upper else upper
                lower = max(lower, prev_lower) if close[idx-1] > prev_lower else lower

            if prev_upper is None:
                trend = 1
            elif close[idx] > prev_upper:
                trend = 1
            elif close[idx] < prev_lower:
                trend = -1

            prev_upper = upper
            prev_lower = lower

        return ts, ltp, trend  # 1 = green, -1 = red

    except Exception as e:
        print(f"❌ fetch_candles error: {e}")
        return None, None, None


def get_atm_strike(index):
    return round(index / 50) * 50


def get_adx():
    if not SENSIBUL_FUTURE_EXPIRY:
        print("❗ SENSIBUL_FUTURE_EXPIRY not configured.")
        return None

    today = datetime.now().strftime("%Y-%m-%d")
    url = f"https://oxide.sensibull.com/v1/compute/candles/{SENSIBUL_FUTURE_EXPIRY}"
    payload = {
        "from_date": today,
        "to_date": today,
        "interval": "1M",
        "skip_last_ts": True
    }

    try:
        data = requests.post(url, json=payload).json()
        c = data["payload"]["candles"]

        high  = [x["high"] for x in c]
        low   = [x["low"] for x in c]
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
        pdi = [(a/b)*100 for a, b in zip(rma(plus_dm, p), tr_r)]
        mdi = [(a/b)*100 for a, b in zip(rma(minus_dm, p), tr_r)]
        dx  = [abs(a-b)/(a+b)*100 if (a+b) != 0 else 0 for a, b in zip(pdi, mdi)]

        return round(rma(dx, p)[-1], 1)

    except Exception as e:
        print(f"❌ ADX error: {e}")
        return None


def fetch_nt_total():
    url = "https://webapi.niftytrader.in/webapi/option/option-chain-data?symbol=nifty&exchange=nse&expiryDate=&atmBelow=2&atmAbove=2"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "accept": "application/json"
    }
    try:
        res = requests.get(url, headers=headers)
        return res.json()
    except Exception as e:
        print(f"❌ NT fetch error: {e}")
        return None


def get_day_change():
    url = "https://webapi.niftytrader.in/webapi/symbol/today-spot-data?symbol=nifty&created_at="
    headers = {
        "User-Agent": "Mozilla/5.0",
        "accept": "application/json"
    }
    try:
        res = requests.get(url, headers=headers)
        data = res.json()
        index  = data["resultData"]["last_trade_price"]
        change = data["resultData"]["change_value"]
        rounded = round(index / 50) * 50
        return index, change, rounded
    except Exception as e:
        print(f"❌ Change fetch error: {e}")
        return None


def option_vwap():
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


def update_coi_history(coi_pcr):
    global COI_HISTORY
    COI_HISTORY.append(coi_pcr)
    if len(COI_HISTORY) > 30:
        COI_HISTORY.pop(0)


def get_coi_avg():
    if not COI_HISTORY:
        return None
    return sum(COI_HISTORY) / len(COI_HISTORY)


def send_telegram_message(msg, imp=True):
    if not TELEGRAM:
        return
    BOT_TOKEN  = "8331147432:AAGSG4mI8d87sWEBsY0qtarAtwWbpa4viq0"
    CHANNEL_ID     = "-1003494200670"
    CHANNEL_ID_IMP = "-1003448158591"
    chat_id = CHANNEL_ID_IMP if imp else CHANNEL_ID
    url  = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": msg}
    try:
        requests.post(url, data=data, timeout=5)
    except Exception as e:
        print("❌ send_telegram_message error:", e)


def format_output(ts, ltp, coi_pcr, change_pts, adx, st):
    time_str     = datetime.fromisoformat(ts).strftime("%H:%M")
    coi_flag     = "🟢" if coi_pcr > 0 else "🔴"
    coi_pcr_k    = round(coi_pcr / 1000, 1)
    change_emoji = "🟢" if change_pts >= 0 else "🔴"
    st_flag      = "🟢ST" if st == 1 else "🔴ST"

    print(f"🕒 {time_str} | {ltp} | {change_pts} {change_emoji} | ADX:{adx} | {st_flag} | {coi_pcr_k}K{coi_flag}")
    send_telegram_message(f"🕒{time_str} | {change_pts} {change_emoji} | ADX:{adx} | {st_flag} | {coi_pcr_k}K{coi_flag}", False)


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


def execute_call_trade(ATM):
    global ACTIVE_POSITION, QTY
    if not before_execution():
        return
    place_atm_order(OPTION_EXPIRY, "C", QTY, ATM)
    ACTIVE_POSITION = 'CALL'
    send_telegram_message("🟢 Entered Call position")
    print("🟢 Entered Call position")


def execute_put_trade(ATM):
    global ACTIVE_POSITION, QTY
    if not before_execution():
        return
    place_atm_order(OPTION_EXPIRY, "P", QTY, ATM)
    ACTIVE_POSITION = 'PUT'
    send_telegram_message("🔴 Entered Put position")
    print("🔴 Entered Put position")


def close_trade():
    global ACTIVE_POSITION
    cancel_all_pending_mis_orders()
    close_all_positions()
    ACTIVE_POSITION = None
    send_telegram_message("❌ Closing all position")
    print("❌ Closing all position")

def auto_close_eod():
    """Auto close all positions at end of day 3:12 PM"""
    now = datetime.now()
    if now.hour == 15 and now.minute >= 12:
        if ACTIVE_POSITION is not None:
            print(f"⏰ 3:12 PM — Auto closing position.")
            close_trade()
        return True  # signal to stop trading for the day
    return False

def monitor_loop():
    global ACTIVE_POSITION, PREV_ADX, LAT_ADX, FIRST_TRADE

    if auto_close_eod():
        return # stop trading 03:12

    ts, ltp, st = fetch_candles()
    if ts is None or ltp is None:
        print(f"{datetime.now().strftime('%H:%M')} | Candle fetch error, skipping…")
        return

    result = option_vwap()
    if result is None:
        print(f"{datetime.now().strftime('%H:%M')} | option_vwap fetch error, skipping…")
        return
    index, change, round_value, coi_pcr, cltp, cvwap, pltp, pvwap = result

    atm = get_atm_strike(index)

    PREV_ADX = LAT_ADX
    LAT_ADX  = get_adx()

    update_coi_history(coi_pcr)
    coi_avg = get_coi_avg()

    format_output(ts, ltp, coi_pcr, change, LAT_ADX, st)

    if st is None or coi_avg is None:
        print(f"{datetime.now().strftime('%H:%M')} | Indicators not ready, skipping…")
        return

    # first trade skip
    if FIRST_TRADE and ACTIVE_POSITION is None:
        FIRST_TRADE = False
        print("ℹ️ First candle — skipping trade.")
        return

    # ── CALL conditions ──────────────────────────────
    # ST green + COI positive + above 30avg + cltp > cvwap
    call_cond_1 = st == 1 and coi_pcr > 0 and coi_pcr > coi_avg and cltp > cvwap
    # ST green + COI negative + below 30avg + cltp > cvwap
    call_cond_2 = st == 1 and coi_pcr < 0 and coi_pcr < coi_avg and cltp > cvwap

    # ── PUT conditions ───────────────────────────────
    # ST red + COI negative + above 30avg + pltp > pvwap
    put_cond_1  = st == -1 and coi_pcr < 0 and coi_pcr > coi_avg and pltp > pvwap
    # ST red + COI positive + below 30avg + pltp > pvwap
    put_cond_2  = st == -1 and coi_pcr > 0 and coi_pcr < coi_avg and pltp > pvwap

    call_entry = call_cond_1 or call_cond_2
    put_entry  = put_cond_1  or put_cond_2

    # ── LONG (Call) Logic ────────────────────────────
    if ACTIVE_POSITION == 'CALL':
        if not call_entry:
            close_trade()

    elif ACTIVE_POSITION is None:
        if call_entry:
            execute_call_trade(atm)

    # ── SHORT (Put) Logic ────────────────────────────
    if ACTIVE_POSITION == 'PUT':
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