import requests
import time
import json
from datetime import datetime
from collections import UserDict
from NorenWebApi import NorenWebApi


################################ cred ############################


userid = "FZ19246"
password = "##"
totp_secret = "35LY6332V5YJ36F5RATW36GJ7J446L43"
app_key = "9e5e9c7220b524ea19a7e6029f5140c423daea49318b23b3b36416549673bac2" # login on web and copy from network tab : quickauth api


# userid = "FZ31096"
# password = "##"
# totp_secret = "V3B3T3AZ3U6236HO35BQRL6S4KP725O5"
# app_key = "" # login on web and copy from network tab : quickauth api


############################## config ###########################


SENSIBUL_FUTURE_EXPIRY = None   # SENSIBUL_FUTURE_EXPIRY = "NIFTY25OCTFUT"
OPTION_EXPIRY = None # "28OCT25"
QTY = None
TRADING_ACTIVE = False  # Fetch from Json Keeper check refresh_vwap_file_config()
FIRST_TRADE = True
ACTIVE_POSITION = None
PREV_ADX = 0
LAT_ADX = 0
TELEGRAM = False




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
    # TRADING_ACTIVE = data.get("TRADING_ACTIVE2", False) # todo
    return SENSIBUL_FUTURE_EXPIRY, OPTION_EXPIRY, QTY, TRADING_ACTIVE

def fetch_vwap():
    if not SENSIBUL_FUTURE_EXPIRY:
        print("❗ SENSIBUL_FUTURE_EXPIRY not configured.")
        return None, None, None
    
    # after 25 of month new month start
    # today = datetime.now().strftime("%Y-%m-%d")
    # now = datetime.now()
    # SENSIBUL_FUTURE_EXPIRY = f"NIFTY{now.strftime('%y')}{now.strftime('%b').upper()}FUT"

    url = f"https://oxide.sensibull.com/v1/compute/candles/{SENSIBUL_FUTURE_EXPIRY}"
    payload = {
        "from_date": today,
        "to_date": today,
        "interval": "1M",
        "skip_last_ts": True
    }

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }

    try:
        res = requests.post(url, headers=headers, json=payload)
        data = res.json()
        candles = data["payload"]["candles"]
        if not candles:
            return None, None, None

        # Collect closes for EMA
        closes = [c["close"] for c in candles]

        # Calculate VWAP
        cum_pv, cum_vol = 0, 0
        for c in candles:
            tp = (c["high"] + c["low"] + c["close"]) / 3
            vol = c["volume"]
            cum_pv += tp * vol
            cum_vol += vol

        vwap = round(cum_pv / cum_vol, 2) if cum_vol else 0

        latest = candles[-1]
        return latest["ts"], latest["close"], vwap

    except Exception as e:
        print(f"❌ VWAP fetch error: {e}")
        return None, None, None

def get_adx():
    if not SENSIBUL_FUTURE_EXPIRY:
        print("❗ SENSIBUL_FUTURE_EXPIRY not configured.")
        return None, None, None, None, None

    today = datetime.now().strftime("%Y-%m-%d")
    url = f"https://oxide.sensibull.com/v1/compute/candles/{SENSIBUL_FUTURE_EXPIRY}"
    payload = {
        "from_date": today,
        "to_date": today,
        "interval": "1M",
        "skip_last_ts": True
    }
    data = requests.post(url, json=payload).json()
    c = data["payload"]["candles"]

    # extract lists
    high  = [x["high"] for x in c]
    low   = [x["low"] for x in c]
    close = [x["close"] for x in c]

    # True Range / DM
    tr = []
    plus_dm = []
    minus_dm = []
    for i in range(1, len(c)):
        tr.append(max(high[i]-low[i],
                      abs(high[i]-close[i-1]),
                      abs(low[i]-close[i-1])))

        up  = high[i]-high[i-1]
        dn  = low[i-1]-low[i]
        plus_dm.append(up if up > dn and up > 0 else 0)
        minus_dm.append(dn if dn > up and dn > 0 else 0)

    # Wilder RMA
    def rma(x, p):
        y = x[:p]
        s = sum(y)/p
        out=[s]
        for v in x[p:]:
            s = (s*(p-1)+v)/p
            out.append(s)
        return out

    p = 14
    tr_r = rma(tr, p)
    p_r  = rma(plus_dm, p)
    m_r  = rma(minus_dm, p)

    pdi = [(a/b)*100 for a,b in zip(p_r, tr_r)]
    mdi = [(a/b)*100 for a,b in zip(m_r, tr_r)]

    dx = [abs(a-b)/(a+b)*100 if (a+b)!=0 else 0
          for a,b in zip(pdi, mdi)]

    adx = rma(dx, p)[-1]
    return round(adx, 1)

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
        index = data["resultData"]["last_trade_price"]
        change = data["resultData"]["change_value"]
        rounded = round(index / 50) * 50
        return index, change, rounded
    except Exception as e:
        print(f"❌ Change fetch error: {e}")
        return None

def strike_vwap():
    index, change, rounded = get_day_change()
    option_chain = fetch_nt_total()

    if not option_chain:
        print("❌ No option chain data")
        return None

    try:
        # coi pcr
        totals = option_chain["resultData"]["opTotals"]["total_calls_puts"]
        coi_pcr = totals["total_puts_change_oi"] - totals["total_calls_change_oi"]
        round_value = rounded - 50 if coi_pcr > 0 else rounded + 50

        data_list = option_chain["resultData"]["opDatas"]
        match = next((item for item in data_list if item["strike_price"] == round_value), None)

        if not match:
            print("⚠️ No matching strike:", rounded)
            return None
        
        cltp = match.get("calls_ltp")
        cvwap = match.get("calls_average_price")
        pltp = match.get("puts_ltp")
        pvwap = match.get("puts_average_price")
        
        return (index, change, round_value, coi_pcr, cltp, cvwap, pltp, pvwap)

    except Exception as e:
        print("❌ Error searching data:", e)

def send_telegram_message(msg, imp=True):
    if not TELEGRAM:
        return
    BOT_TOKEN = "8331147432:AAGSG4mI8d87sWEBsY0qtarAtwWbpa4viq0" # zapy
    CHANNEL_ID = "-1003494200670"   # your flatxx channel ID
    CHANNEL_ID_IMP = "-1003448158591"   # your flatxx imp channel ID

    chat_id = CHANNEL_ID_IMP if imp else CHANNEL_ID

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": msg}
    try:
        requests.post(url, data=data, timeout=5)
    except Exception as e:
        print("❌ send_telegram_message error:", e)

def format_output(ts, ltp, vwap, coi_pcr, change_pts, LAT_ADX):
    time_str = datetime.fromisoformat(ts).strftime("%H:%M")
    vwap_flag = "🟢" if ltp > vwap else "🔴"
    coi_flag = "🟢" if coi_pcr > 0 else "🔴"
    coi_pcr_k = round(coi_pcr / 1000, 1)
    change_emoji = "🟢" if change_pts >= 0 else "🔴"

    send_telegram_message(f"🕒{time_str} | {change_pts} {change_emoji} | Adx:{LAT_ADX} | {vwap}{vwap_flag} | {coi_pcr_k}K{coi_flag}", False)
    print(f"🕒 {time_str} | {ltp} | {change_pts} {change_emoji} | Adx : {LAT_ADX} | {vwap}{vwap_flag} | {coi_pcr_k}K{coi_flag}")

def calculate_realized_pnl():
    position_book = api.get_positions() or []

    if not position_book or isinstance(position_book, dict):
        print("⚠️ No valid positions found or API returned error. Returning PnL = 0.")
        return 0.0
    
    # print('POS', position_book)
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
    
    # New code with exception
    canceled_count = 0

    for order in orders:
        try:
            # Check if order is pending and type is MIS
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

def before_execution():
    try:
        pnl = calculate_realized_pnl()
        print(f"Realized PNL: {pnl}")
    except Exception as e:
        print(f"Error calculating PNL: {e}")
        return

    # ✅ Skip trade if loss exceeds threshold
    if pnl < -4000:
        print("⚠️ Loss exceeds -4000, skipping trade execution.")
        return False

    cancel_all_pending_mis_orders()
    close_all_positions()
    return True  # ready to trade

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

    return resp

def execute_call_trade():
    global ACTIVE_POSITION, FIRST_TRADE, QTY

    # 🟡 Skip the first CALL trade only once
    if FIRST_TRADE and ACTIVE_POSITION != 'CALL':
        ACTIVE_POSITION = 'CALL'
        FIRST_TRADE = False
        print("⏸ Skipping first CALL trade (initial trigger).")
        return

    if not before_execution():
        return
    place_atm_order(OPTION_EXPIRY, "C", QTY)
    ACTIVE_POSITION = 'CALL'
    send_telegram_message("🟢 Entered Call position")
    print("🟢 Entered Call position")

def execute_put_trade():
    global ACTIVE_POSITION, FIRST_TRADE, QTY

    # 🟡 Skip the first PUT trade only once
    if FIRST_TRADE and ACTIVE_POSITION != 'PUT':
        ACTIVE_POSITION = 'PUT'
        FIRST_TRADE = False
        print("⏸ Skipping first PUT trade (initial trigger).")
        return

    if not before_execution():
        return
    place_atm_order(OPTION_EXPIRY, "P", QTY)
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

def monitor_loop():
    global ACTIVE_POSITION, PREV_ADX, LAT_ADX

    ts, ltp, vwap = fetch_vwap()
    index, change, round_value, coi_pcr, cltp, cvwap, pltp, pvwap = strike_vwap()

    PREV_ADX = LAT_ADX
    LAT_ADX = get_adx()

    if ts is None or ltp is None or vwap is None or coi_pcr is None or change is None:
        print(f"{datetime.now().strftime('%H:%M')} | Data fetch error, skipping…")
        return  # Skip without sleeping here; sleep is in main loop

    format_output(ts, ltp, vwap, coi_pcr, change, LAT_ADX)
    
    # Long (Call) Logic
    if ACTIVE_POSITION == 'CALL':
        if (cltp is None or cvwap is None) or ((cltp < cvwap) or (pltp is not None and pltp > pvwap) or (ltp < vwap)):
            close_trade()

    elif ACTIVE_POSITION is None:
        if ltp > vwap and cltp > cvwap and coi_pcr > 0:
            execute_call_trade()

    # Short (Put) Logic
    if ACTIVE_POSITION == 'PUT':
        if (pltp is None or pvwap is None) or ((pltp < pvwap) or (cltp is not None and cltp > cvwap) or (ltp > vwap)):
            close_trade()

    elif ACTIVE_POSITION is None:
        if ltp < vwap and pltp > pvwap and coi_pcr < 0:
            execute_put_trade()

if __name__ == "__main__":
    # generate_token()
    # ok = refresh_token()
    # if not ok:
    #     print("Token unavailable. Exiting.")
    #     exit(1)

    api = NorenWebApi()
    try:
        login = api.login(userid=userid, password=password, totp_secret=totp_secret,app_key=app_key)
    except Exception as e:
        print("Login Failed:", str(e))
        send_telegram_message(f"❌ Login Error: {str(e)}")

    refresh_vwap_file_config()

    if not SENSIBUL_FUTURE_EXPIRY:
        print("No SENSIBUL_FUTURE_EXPIRY configured. Exiting.")
        exit(1)
   
    while True:
        try:
            refresh_vwap_file_config()  # Refresh config every minute for runtime updates
            
            if not TRADING_ACTIVE:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Trading inactive. Sleeping for 1 minute...")
                time.sleep(60)
                continue

            try:
                monitor_loop()
            except Exception as e:
                print(f"❌ Monitor error: {e}")

            time.sleep(60)

        except KeyboardInterrupt:
            print("🛑 Monitor stopped by user.")
            break

        except Exception as e:
            print(f"🔥 FATAL loop crash: {e}")
            time.sleep(30)  # prevent instant restart loop if repeated crash