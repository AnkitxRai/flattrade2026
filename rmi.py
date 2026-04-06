#!/usr/bin/env python3
"""
NIFTY Options Bot — RMI Trend Sniper
Entry : positive flips True + RWMA blue → CALL
        negative flips True + RWMA red  → PUT
Exit  : opposite signal OR 15:12
"""

import requests
import time
from datetime import datetime, timedelta
from NorenWebApi import NorenWebApi

################################ cred ############################

userid       = "FZ19246"
password     = "##"
totp_secret  = "35LY6332V5YJ36F5RATW36GJ7J446L43"
app_key      = "9e5e9c7220b524ea19a7e6029f5140c423daea49318b23b3b36416549673bac2"

############################## config ###########################

SENSIBUL_FUTURE_EXPIRY = None
OPTION_EXPIRY          = None
QTY                    = None
TRADING_ACTIVE         = False
FIRST_TRADE            = True
ACTIVE_POSITION        = None
ENTRY_STRIKE           = None
TELEGRAM               = True

# ─── RMI PARAMS ───
RMI_LEN  = 14
PMOM     = 66
NMOM     = 30
EMA_LEN  = 5

# ─── STATE ───
rmi_positive = False
rmi_negative = False

# ─────────────────────────────────────────────
# Fetch Strike OI and VWAP Data
# ─────────────────────────────────────────────
def fetch_nt_total():
    url     = "https://webapi.niftytrader.in/webapi/option/option-chain-data?symbol=nifty&exchange=nse&expiryDate=&atmBelow=5&atmAbove=5"
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
    url     = f"https://webapi.niftytrader.in/webapi/Option/option-chain-calculator-data?symbol=nifty&expiryDate=&createdTime={created_time}&isloader=false&atmBelow=5&atmAbove=5"
    headers = {"User-Agent": "Mozilla/5.0", "accept": "application/json"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        if not data or not isinstance(data, dict):
            print(f"❌ NT expiry bad response"); return None
        return data
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
        dates = data["resultData"]["opExpiryDates"]
        today = datetime.now().date()

        def trading_days(from_date, to_date):
            count = 0
            d = from_date
            while d <= to_date:
                if d.weekday() < 5:
                    count += 1
                d += timedelta(days=1)
            return count

        def to_expiry_fmt(iso_str):
            dt = datetime.fromisoformat(iso_str)
            return dt.strftime("%d%b%y").upper()

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
    global SENSIBUL_FUTURE_EXPIRY, QTY, TRADING_ACTIVE
    json_url = "https://www.jsonkeeper.com/b/EDZIR"
    try:
        resp = requests.get(json_url, timeout=10)
        data = resp.json()
        if not isinstance(data, dict):
            print(f"⚠️ Invalid config format"); return
    except Exception as e:
        print(f"❌ Config fetch failed: {e}"); return
    SENSIBUL_FUTURE_EXPIRY = data.get("SENSIBUL_FUTURE_EXPIRY")
    QTY                    = data.get("QTY")
    TRADING_ACTIVE         = data.get("TRADING_ACTIVE", False)


# ─────────────────────────────────────────────
# FETCH CANDLES + COMPUTE RMI TREND SNIPER
# ─────────────────────────────────────────────
def fetch_candles_rmi():
    global rmi_positive, rmi_negative

    today    = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")

    url     = f"https://oxide.sensibull.com/v1/compute/2/candles/{SENSIBUL_FUTURE_EXPIRY or 'NIFTY26APRFUT'}"
    print(url)
    payload = {
        "from_date":    week_ago,
        "to_date":      today,
        "interval":     "5M",
        "skip_last_ts": True,
    }

    try:
        resp    = requests.post(url, json=payload, timeout=15)
        candles = resp.json().get("payload", {}).get("candles", [])
        if not candles:
            print("⚠️ No candle data received")
            return None, None, None

        if len(candles) < RMI_LEN + 5:
            print(f"⚠️ Not enough candles: {len(candles)}")
            return None, None, None

        hi  = [c["high"]   for c in candles]
        lo  = [c["low"]    for c in candles]
        cl  = [c["close"]  for c in candles]
        vol = [c["volume"] for c in candles]
        ts_list = [c["ts"] for c in candles]

        # ── RMA ──
        def rma(series, length):
            alpha = 1.0 / length
            out   = [float('nan')] * len(series)
            out[length - 1] = sum(series[:length]) / length
            for i in range(length, len(series)):
                out[i] = alpha * series[i] + (1 - alpha) * out[i - 1]
            return out

        # ── RSI ──
        change  = [0.0] + [cl[i] - cl[i-1] for i in range(1, len(cl))]
        up_s    = rma([max(x, 0) for x in change], RMI_LEN)
        down_s  = rma([max(-x, 0) for x in change], RMI_LEN)
        rsi     = []
        for u, d in zip(up_s, down_s):
            if float('nan') in [u, d] or (u != u) or (d != d):
                rsi.append(float('nan'))
            elif d == 0:
                rsi.append(100.0)
            elif u == 0:
                rsi.append(0.0)
            else:
                rsi.append(100 - (100 / (1 + u / d)))

        # ── MFI (rolling sum) ──
        hlc3        = [(hi[i] + lo[i] + cl[i]) / 3 for i in range(len(cl))]
        hlc3_change = [0.0] + [hlc3[i] - hlc3[i-1] for i in range(1, len(hlc3))]
        pos_mf      = [vol[i] * hlc3[i] if hlc3_change[i] > 0 else 0.0 for i in range(len(cl))]
        neg_mf      = [vol[i] * hlc3[i] if hlc3_change[i] < 0 else 0.0 for i in range(len(cl))]

        def rolling_sum(series, length):
            out = [float('nan')] * len(series)
            for i in range(length - 1, len(series)):
                out[i] = sum(series[i - length + 1: i + 1])
            return out

        pos_sum = rolling_sum(pos_mf, RMI_LEN)
        neg_sum = rolling_sum(neg_mf, RMI_LEN)
        mfi     = []
        for p, n in zip(pos_sum, neg_sum):
            if p != p or n != n:
                mfi.append(float('nan'))
            elif n == 0:
                mfi.append(100.0)
            elif p == 0:
                mfi.append(0.0)
            else:
                mfi.append(100 - (100 / (1 + p / n)))

        # ── rsi_mfi ──
        rsi_mfi = [(rsi[i] + mfi[i]) / 2 if (rsi[i] == rsi[i] and mfi[i] == mfi[i])
                   else float('nan') for i in range(len(cl))]

        # ── EMA5 change ──
        ema5 = [float('nan')] * len(cl)
        k    = 2 / (EMA_LEN + 1)
        for i in range(len(cl)):
            if i == 0:
                ema5[i] = cl[i]
            else:
                prev = ema5[i-1] if ema5[i-1] == ema5[i-1] else cl[i]
                ema5[i] = cl[i] * k + prev * (1 - k)
        ema5_change = [0.0] + [ema5[i] - ema5[i-1] for i in range(1, len(ema5))]

        # ── p_mom / n_mom ──
        p_mom = []
        n_mom = []
        for i in range(len(cl)):
            if i == 0:
                p_mom.append(False); n_mom.append(False); continue
            rm_prev = rsi_mfi[i-1]
            rm_curr = rsi_mfi[i]
            if rm_prev != rm_prev or rm_curr != rm_curr:
                p_mom.append(False); n_mom.append(False); continue
            p_mom.append(rm_prev < PMOM and rm_curr > PMOM and rm_curr > NMOM and ema5_change[i] > 0)
            n_mom.append(rm_curr < NMOM and ema5_change[i] < 0)

        # ── Stateful positive/negative — reset at each new day ──
        positive = []
        negative = []
        pos = False
        neg = False
        prev_date = None

        for i in range(len(cl)):
            cur_date = datetime.fromisoformat(ts_list[i]).date()
            if prev_date is not None and cur_date != prev_date:
                pos = False
                neg = False
            prev_date = cur_date
            if p_mom[i]:
                pos = True;  neg = False
            if n_mom[i]:
                pos = False; neg = True
            positive.append(pos)
            negative.append(neg)

        # ── Current and previous bar ──
        pos_now  = positive[-1]
        neg_now  = negative[-1]
        pos_prev = positive[-2]
        neg_prev = negative[-2]

        buy_signal  = pos_now and not pos_prev
        sell_signal = neg_now and not neg_prev

        # ── Update global state ──
        rmi_positive = pos_now
        rmi_negative = neg_now

        latest_ts  = ts_list[-1]
        latest_ltp = cl[-1]

        rmi_data = {
            "buy_signal"  : buy_signal,
            "sell_signal" : sell_signal,
            "positive"    : pos_now,
            "negative"    : neg_now,
            "rsi_mfi"     : round(rsi_mfi[-1], 2) if rsi_mfi[-1] == rsi_mfi[-1] else None,
        }

        return latest_ts, latest_ltp, rmi_data

    except Exception as e:
        print(f"❌ fetch_candles_rmi error: {e}")
        import traceback; traceback.print_exc()
        return None, None, None


def get_atm_strike(index):
    return round(index / 50) * 50


def get_day_change():
    url     = "https://webapi.niftytrader.in/webapi/symbol/today-spot-data?symbol=nifty&created_at="
    headers = {"User-Agent": "Mozilla/5.0", "accept": "application/json"}
    try:
        data    = requests.get(url, headers=headers, timeout=10).json()
        result  = data.get("resultData", {})
        index   = result.get("last_trade_price")
        change  = result.get("change_value")
        if index is None or change is None:
            print("⚠️ Spot data missing"); return None
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
        totals = option_chain.get("resultData", {}).get("opTotals", {}).get("total_calls_puts", {})
        if not totals:
            print("⚠️ OI totals missing"); return None
        coi_pcr     = totals.get("total_puts_change_oi", 0) - totals.get("total_calls_change_oi", 0)
        round_value = locked_strike if locked_strike is not None else (rounded - 50 if coi_pcr > 0 else rounded + 50)

        data_list = option_chain.get("resultData", {}).get("opDatas", [])
        if not data_list:
            print("⚠️ Option chain data missing"); return None

        match = next((item for item in data_list if item["strike_price"] == round_value), None)
        if not match:
            print("⚠️ No matching strike:", round_value); return None

        return (
            index, change, round_value, coi_pcr,
            match.get("calls_ltp"),      match.get("calls_average_price"),
            match.get("puts_ltp"),       match.get("puts_average_price"),
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


def format_output(ts, ltp, coi_pcr, change_pts, rmi_data):
    time_str     = datetime.fromisoformat(ts).strftime("%H:%M")
    coi_flag     = "🟢" if coi_pcr > 0 else "🔴"
    coi_pcr_k    = round(coi_pcr / 1000, 1)
    change_emoji = "🟢" if change_pts >= 0 else "🔴"
    rmi_str      = f"RMI:{rmi_data['rsi_mfi']}" if rmi_data and rmi_data['rsi_mfi'] else "RMI:--"
    color_str    = "🔵" if rmi_data and rmi_data["positive"] else ("🔴" if rmi_data and rmi_data["negative"] else "⚪")
    sig_str      = "▲BUY" if rmi_data and rmi_data["buy_signal"] else ("▼SELL" if rmi_data and rmi_data["sell_signal"] else "")

    print(f"🕒 {time_str} | {ltp} | {change_pts} {change_emoji} | {color_str} {rmi_str} {sig_str} | {coi_pcr_k}K{coi_flag}")
    send_telegram_message(f"🕒{time_str} | {change_pts} {change_emoji} | {color_str} {rmi_str} {sig_str} | {coi_pcr_k}K{coi_flag}", False)


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

    # ── Fetch candles + compute RMI ──
    ts, ltp, rmi_data = fetch_candles_rmi()
    if ts is None or ltp is None or rmi_data is None:
        print(f"{datetime.now().strftime('%H:%M')} | Candle/RMI fetch error, skipping…")
        return

    # ── Fetch option vwap ──
    result = option_vwap(locked_strike=ENTRY_STRIKE)
    if result is None:
        print(f"{datetime.now().strftime('%H:%M')} | option_vwap error, skipping…")
        return
    index, change, round_value, coi_pcr, cltp, cvwap, pltp, pvwap = result

    atm = get_atm_strike(index)

    format_output(ts, ltp, coi_pcr, change, rmi_data)

    # ── Skip first candle ──
    if FIRST_TRADE and ACTIVE_POSITION is None:
        FIRST_TRADE = False
        print("ℹ️ First candle — skipping trade.")
        return

    buy_signal  = rmi_data["buy_signal"]
    sell_signal = rmi_data["sell_signal"]
    positive    = rmi_data["positive"]
    negative    = rmi_data["negative"]

    # ── CALL logic ──
    # Entry: RMI buy signal + RWMA blue (positive)
    # ── CALL logic ──
    if ACTIVE_POSITION == "CALL":
        if negative:
            print("🔄 RMI flipped negative — closing CALL")
            close_trade()
    elif ACTIVE_POSITION is None:
        if buy_signal:
            execute_call_trade(atm)

    # ── PUT logic ──
    if ACTIVE_POSITION == "PUT":
        if positive:
            print("🔄 RMI flipped positive — closing PUT")
            close_trade()
    elif ACTIVE_POSITION is None:
        if sell_signal:
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
                import traceback; traceback.print_exc()

            now        = datetime.now()
            sleep_time = max(5, 65 - now.second)
            time.sleep(sleep_time)

        except KeyboardInterrupt:
            print("🛑 Stopped by user.")
            break
        except Exception as e:
            print(f"🔥 FATAL: {e}")
            time.sleep(30)