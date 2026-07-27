import os
# ضبط التوقيت ليكون بتوقيت الجزائر المحلي
os.environ['TZ'] = 'Africa/Algiers'
import time
import http.server
import socketserver
import threading
import httpx
import pandas as pd
import ta
import yfinance as yf
from datetime import datetime, timedelta

# تشغيل خادم الويب في الخلفية ليتوافق مع متطلبات Render المجانية
def run_server():
    PORT = int(os.environ.get("PORT", 8080))
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        httpd.serve_forever()

threading.Thread(target=run_server, daemon=True).start()

# 1. إعدادات التلجرام (تم اعتماد الرمز والآي دي الخاص بك)
TOKEN = "8952348741:AAFbfBHqJrJpOupJBrctXomZfZ64F9isGf4"
CHAT_ID = "8463817127"

# 2. الحد الأدنى للفاصل الزمني بين الصفقات العامة (300 ثانية = 5 دقائق)
MIN_SIGNAL_INTERVAL = 300  

active_trades = []
news_events_cache = []
last_news_fetch_time = 0

SYMBOLS = {
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "USDJPY=X": "USD/JPY",
    "AUDUSD=X": "AUD/USD",
    "USDCAD=X": "USD/CAD",
    "USDCHF=X": "USD/CHF",
    "NZDUSD=X": "NZD/USD",
    "EURGBP=X": "EUR/GBP",
    "EURJPY=X": "EUR/JPY",
    "GBPJPY=X": "GBP/JPY",
    "AUDJPY=X": "AUD/JPY",
    "EURAUD=X": "EUR/AUD",
    "GBPAUD=X": "GBP/AUD",
    "GC=F": "الذهب (Gold)",
    "CL=F": "النفط (Crude Oil)",
    "^GSPC": "مؤشر S&P 500"
}

# -------------------------------------------------------------
# دالة إرسال الرسائل المدعومة بالأزرار التفاعلية
# -------------------------------------------------------------
def send_telegram_message(message, reply_markup=None):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        with httpx.Client(verify=True, timeout=10.0) as client:
            response = client.post(url, json=payload)
            return response.status_code == 200
    except Exception as e:
        print(f"❌ خطأ أثناء الإرسال: {e}")
        return False

# -------------------------------------------------------------
# جلب وفحص الأخبار الاقتصادية
# -------------------------------------------------------------
def fetch_economic_news():
    global news_events_cache, last_news_fetch_time
    current_time = time.time()
    
    if current_time - last_news_fetch_time < 3600 and news_events_cache:
        return news_events_cache

    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        with httpx.Client(verify=True, timeout=10.0) as client:
            res = client.get(url)
            if res.status_code == 200:
                data = res.json()
                high_impact_news = []
                for item in data:
                    if item.get('impact') == 'High':
                        news_dt = datetime.fromisoformat(item['date'].replace('Z', '+00:00'))
                        news_dt = news_dt.astimezone().replace(tzinfo=None)
                        high_impact_news.append({
                            'title': item.get('title'),
                            'country': item.get('country'),
                            'time': news_dt
                        })
                news_events_cache = high_impact_news
                last_news_fetch_time = current_time
                print(f"📰 تم تحديث تقويم الأخبار بنجاح! ({len(high_impact_news)} خبر قوي هذا الأسبوع)")
                return news_events_cache
    except Exception as e:
        print(f"⚠️ تعذر جلب الأخبار الاقتصادية: {e}")
    
    return news_events_cache

def is_news_time(symbol, pair_name):
    news_list = fetch_economic_news()
    if not news_list:
        return False

    now = datetime.now()
    currencies = []
    if "/" in pair_name:
        currencies = pair_name.split("/")
    elif "الذهب" in pair_name or "النفط" in pair_name or "S&P" in pair_name:
        currencies = ["USD"]

    for news in news_list:
        if news['country'] in currencies:
            news_time = news['time']
            time_diff = abs((now - news_time).total_seconds()) / 60.0
            if time_diff <= 15:
                print(f"🚫 [فلتر الأخبار] حظر التداول على {pair_name} بسبب خبر: {news['title']}")
                return True
                
    return False

# -------------------------------------------------------------
# تحليل السوق وجلب البيانات (النسخة الاحترافية العليا)
# -------------------------------------------------------------
def get_market_data(symbol, interval="5m", period="5d"):
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)
        if df.empty or len(df) < 200:
            return None
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df = df.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'})
        return df
    except Exception as e:
        print(f"⚠️ خطأ في جلب بيانات {symbol}: {e}")
        return None

def is_smart_candle(candle):
    total_length = candle['high'] - candle['low']
    body_length = abs(candle['close'] - candle['open'])
    if total_length == 0:
        return False
    return (body_length / total_length) >= 0.60

def analyze_market(df):
    if df is None or len(df) < 200:
        return "HOLD", 0, 0, 0

    df['sma_fast'] = ta.trend.sma_indicator(df['close'], window=10)
    df['sma_slow'] = ta.trend.sma_indicator(df['close'], window=30)
    df['rsi'] = ta.momentum.rsi(df['close'], window=14)
    df['ema_trend'] = ta.trend.ema_indicator(df['close'], window=200)

    df['atr'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=14)
    df['atr_ma'] = df['atr'].rolling(window=20).mean()

    bb = ta.volatility.BollingerBands(close=df['close'], window=20, window_dev=2)
    df['bb_high'] = bb.bollinger_hband()
    df['bb_low'] = bb.bollinger_lband()

    macd = ta.trend.MACD(close=df['close'])
    df['macd_diff'] = macd.macd_diff()
    df['adx'] = ta.trend.adx(df['high'], df['low'], df['close'], window=14)
    
    latest = df.iloc[-1]
    previous = df.iloc[-2]

    # 1. فلتر السيولة والتذبذب
    has_enough_volatility = latest['atr'] > (latest['atr_ma'] * 0.8)
    smart_candle_valid = is_smart_candle(latest)

    if not has_enough_volatility:
        return "HOLD", latest['close'], latest['rsi'], 0

    # 2. فلتر قوة الشمعة السابقة
    prev_body = abs(previous['close'] - previous['open'])
    prev_range = previous['high'] - previous['low']
    is_strong_prev_candle = (prev_range > 0) and ((prev_body / prev_range) >= 0.50)

    prev_is_green = previous['close'] > previous['open']
    prev_is_red = previous['close'] < previous['open']

    # 3. حساب مستويات الدعم والمقاومة السريعة
    recent_high = df['high'].iloc[-20:-1].max()
    recent_low = df['low'].iloc[-20:-1].min()

    signal = "HOLD"
    confidence = 0

    # اتجاه الشراء (CALL)
    if latest['close'] > latest['ema_trend'] and smart_candle_valid and prev_is_green and is_strong_prev_candle: 
        if (recent_high - latest['close']) > (latest['atr'] * 0.5):
            if (previous['sma_fast'] <= previous['sma_slow']) and (latest['sma_fast'] > latest['sma_slow']):
                signal = "BUY"
                confidence = 80
            elif latest['close'] <= latest['bb_low']:
                signal = "BUY"
                confidence = 80

            if signal == "BUY":
                if latest['rsi'] < 40:
                    confidence += 10
                if latest['macd_diff'] > 0 and previous['macd_diff'] < latest['macd_diff']:
                    confidence += 10

    # اتجاه البيع (PUT)
    if latest['close'] < latest['ema_trend'] and smart_candle_valid and prev_is_red and is_strong_prev_candle:
        if (latest['close'] - recent_low) > (latest['atr'] * 0.5):
            if (previous['sma_fast'] >= previous['sma_slow']) and (latest['sma_fast'] < latest['sma_slow']):
                signal = "SELL"
                confidence = 80
            elif latest['close'] >= latest['bb_high']:
                signal = "SELL"
                confidence = 80

            if signal == "SELL":
                if latest['rsi'] > 60:
                    confidence += 10
                if latest['macd_diff'] < 0 and previous['macd_diff'] > latest['macd_diff']:
                    confidence += 10

    confidence = min(confidence, 95)
    return signal, latest['close'], latest['rsi'], confidence

# -------------------------------------------------------------
# فحص وتتبع النتائج
# -------------------------------------------------------------
def check_active_trades():
    global active_trades
    now = datetime.now()
    trades_to_remove = []

    for trade in active_trades:
        if now >= trade['expiry_datetime']:
            df = get_market_data(trade['symbol'], interval="1m", period="1d")
            if df is not None and not df.empty:
                exit_price = df.iloc[-1]['close']
                entry_price = trade['entry_price']
                signal = trade['signal']

                is_win = False
                if signal == "BUY" and exit_price > entry_price:
                    is_win = True
                elif signal == "SELL" and exit_price < entry_price:
                    is_win = True

                status_emoji = "🟢 صفقة ناجحة (WIN)" if is_win else "🔴 صفقة خاسرة (LOSS)"
                direction_str = "شراء" if signal == "BUY" else "بيع"

                result_msg = (
                    f"📊 <b>تقرير نتيجة الصفقة!</b>\n\n"
                    f"📊 الزوج: <b>{trade['pair_name']}</b>\n"
                    f"📈 الاتجاه: <b>{direction_str}</b>\n"
                    f"💵 سعر الدخول: <code>{entry_price:.5f}</code>\n"
                    f"🏁 سعر الإغلاق: <code>{exit_price:.5f}</code>\n\n"
                    f"🏆 النتيجة: <b>{status_emoji}</b>"
                )
                send_telegram_message(result_msg)
                print(f"🏁 [{trade['pair_name']}] نتيجة الصفقة: {'WIN' if is_win else 'LOSS'}")
                trades_to_remove.append(trade)

    for trade in trades_to_remove:
        active_trades.remove(trade)

# -------------------------------------------------------------
# التشغيل الرئيسي للبوت
# -------------------------------------------------------------
if __name__ == "__main__":
    send_telegram_message("🚀 <b>تم تفعيل البوت للعمل على مدار 24 ساعة بدون قيود زمنية!</b>")
    print("🤖 البوت يعمل الآن ويراقب الأسواق مستمراً...")
    
    last_signals = {symbol: "HOLD" for symbol in SYMBOLS}
    last_global_signal_time = 0

    while True:
        try:
            now = datetime.now()
            weekday = now.weekday()

            # إيقاف التداول فقط في عطلة نهاية الأسبوع (السبت والأحد)
            if weekday in [5, 6]:
                print("🛑 السوق مغلق حالياً (عطلة نهاية الأسبوع)...")
                time.sleep(3600)
                continue

            current_time = time.time()
            check_active_trades()

            for symbol, pair_name in SYMBOLS.items():
                if is_news_time(symbol, pair_name):
                    continue

                df = get_market_data(symbol, interval="5m")
                signal, price, rsi_val, confidence = analyze_market(df)

                if signal in ["BUY", "SELL"] and signal != last_signals[symbol] and confidence >= 85:
                    time_since_last_signal = current_time - last_global_signal_time

                    if time_since_last_signal >= MIN_SIGNAL_INTERVAL:
                        direction_ar = "🟢 شراء (CALL)" if signal == "BUY" else "🔴 بيع (PUT)"
                        conf_emoji = "🔥 فرصة فائقة الدقة" if confidence >= 90 else "⚡ فرصة ممتازة جداً"

                        next_candle_minute = ((now.minute // 5) + 1) * 5
                        if next_candle_minute >= 60:
                            entry_datetime = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                        else:
                            entry_datetime = now.replace(minute=next_candle_minute, second=0, microsecond=0)

                        expiry_datetime = entry_datetime + timedelta(minutes=5)
                        entry_time = entry_datetime.strftime("%H:%M:%S")

                        msg = (
                            f"🎯 <b>تنبيه صفقة عالية الجودة والفلترة!</b>\n\n"
                            f"📊 الزوج: <b>{pair_name}</b>\n"
                            f"📈 الاتجاه: <b>{direction_ar}</b>\n"
                            f"🎯 <b>نسبة الثقة: {confidence}%</b> ({conf_emoji})\n\n"
                            f"⏰ <b>وقت الدخول:</b> <code>{entry_time}</code> (بداية الشمعة)\n"
                            f"⏱️ <b>مدة الصفقة:</b> <b>5 دقائق بالضبط</b>\n\n"
                            f"💵 السعر الحالي: <code>{price:.5f}</code>\n"
                            f"📊 RSI: <code>{rsi_val:.1f}</code>\n"
                            f"🛡️ <b>الفلاتر المفعلة:</b> الأخبار + ATR + الشمعة القوية + EMA 200 + MACD Impulse + الدعم/المقاومة"
                        )

                        keyboard = {
                            "inline_keyboard": [
                                [
                                    {"text": "📲 فتح منصة Pocket Option", "url": "https://pocketoption.com"}
                                ],
                                [
                                    {"text": "💵 $1", "callback_data": "amt_1"},
                                    {"text": "💵 $2", "callback_data": "amt_2"},
                                    {"text": "💵 $5", "callback_data": "amt_5"},
                                    {"text": "💵 $10", "callback_data": "amt_10"}
                                ],
                                [
                                    {"text": "🛡️ الفلاتر المفعلة", "callback_data": "show_filters"},
                                    {"text": "⏱️ الإطار: 5m", "callback_data": "show_time"}
                                ]
                            ]
                        }

                        send_telegram_message(msg, reply_markup=keyboard)
                        print(f"✅ [{pair_name}] إشارة {signal} مؤكدة بنسبة {confidence}% عند الساعة {entry_time}")
                        
                        active_trades.append({
                            'symbol': symbol,
                            'pair_name': pair_name,
                            'signal': signal,
                            'entry_price': price,
                            'entry_datetime': entry_datetime,
                            'expiry_datetime': expiry_datetime
                        })

                        last_signals[symbol] = signal
                        last_global_signal_time = current_time
                    else:
                        print(f"⏳ [{pair_name}] تم تأجيل الإشارة مؤقته لتجنب التداخل.")
                else:
                    if signal == "HOLD":
                        last_signals[symbol] = "HOLD"
                    print(f"⏳ [{pair_name}] | حالة: {signal} | سعر: {price:.5f} | RSI: {rsi_val:.1f} | ثقة: {confidence}%")

            time.sleep(60)

        except KeyboardInterrupt:
            print("\n⛔ تم إيقاف البوت.")
            break
        except Exception as e:
            print(f"❌ خطأ غير متوقع: {e}")
            time.sleep(10)
            
