import os
import time
import requests
import yfinance as yf
import pandas as pd
import ta

# بيانات بوت التليجرام
TELEGRAM_TOKEN = "8952348741:AAFbfBHqJrJpOupJBrctXomZfZ64F9isGf4"
TELEGRAM_CHAT_ID = "8463817127"

# القائمة الذهبية المصممة خصيصاً وفق نتائج الاختبار العكسي
GOLDEN_CONFIGS = {
    "EURUSD=X": {"name": "EUR/USD", "tf": "5m", "htf": "15m"},
    "GBPUSD=X": {"name": "GBP/USD", "tf": "5m", "htf": "15m"},
    "USDJPY=X": {"name": "USD/JPY", "tf": "5m", "htf": "15m"},
    "AUDUSD=X": {"name": "AUD/USD", "tf": "15m", "htf": "1h"},
    "USDCHF=X": {"name": "USD/CHF", "tf": "5m", "htf": "15m"},
    "NZDUSD=X": {"name": "NZD/USD", "tf": "5m", "htf": "15m"},
    "EURGBP=X": {"name": "EUR/GBP", "tf": "1m", "htf": "5m"},
    "EURJPY=X": {"name": "EUR/JPY", "tf": "5m", "htf": "15m"},
    "GBPJPY=X": {"name": "GBP/JPY", "tf": "1m", "htf": "5m"},
    "CHFJPY=X": {"name": "CHF/JPY", "tf": "5m", "htf": "15m"},
    "NZDJPY=X": {"name": "NZD/JPY", "tf": "15m", "htf": "1h"},
    "GC=F":     {"name": "الذهب (Gold)", "tf": "15m", "htf": "1h"},
    "CL=F":     {"name": "النفط (Crude Oil)", "tf": "5m", "htf": "15m"},
    "^GSPC":    {"name": "مؤشر S&P 500", "tf": "1m", "htf": "5m"}
}

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"❌ خطأ إرسال التليجرام: {e}")

def is_smart_candle(candle):
    total_length = candle['high'] - candle['low']
    body_length = abs(candle['close'] - candle['open'])
    if total_length == 0:
        return False
    return (body_length / total_length) >= 0.55

def check_signal(symbol, config):
    pair_name = config["name"]
    entry_tf = config["tf"]
    htf_tf = config["htf"]

    try:
        ticker = yf.Ticker(symbol)
        df_entry = ticker.history(period="5d", interval=entry_tf)
        df_htf = ticker.history(period="5d", interval=htf_tf)

        if df_entry.empty or len(df_entry) < 200 or df_htf.empty or len(df_htf) < 200:
            return

        if df_entry.index.tz is not None:
            df_entry.index = df_entry.index.tz_localize(None)
        if df_htf.index.tz is not None:
            df_htf.index = df_htf.index.tz_localize(None)

        df_entry = df_entry.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close'})
        df_htf = df_htf.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close'})

        df_htf['htf_ema'] = ta.trend.ema_indicator(df_htf['close'], window=200)

        df_entry['sma_fast'] = ta.trend.sma_indicator(df_entry['close'], window=10)
        df_entry['sma_slow'] = ta.trend.sma_indicator(df_entry['close'], window=30)
        df_entry['ema_trend'] = ta.trend.ema_indicator(df_entry['close'], window=200)

        df_entry['atr'] = ta.volatility.average_true_range(df_entry['high'], df_entry['low'], df_entry['close'], window=14)
        df_entry['atr_ma'] = df_entry['atr'].rolling(window=20).mean()

        bb = ta.volatility.BollingerBands(close=df_entry['close'], window=20, window_dev=2)
        df_entry['bb_high'] = bb.bollinger_hband()
        df_entry['bb_low'] = bb.bollinger_lband()

        latest = df_entry.iloc[-1]
        previous = df_entry.iloc[-2]

        htf_latest = df_htf.iloc[-1]
        htf_bullish = htf_latest['close'] > htf_latest['htf_ema']
        htf_bearish = htf_latest['close'] < htf_latest['htf_ema']


        htf_bullish = htf_latest['close'] > htf_latest['htf_ema']
        htf_bearish = htf_latest['close'] < htf_latest['htf_ema']

        if latest['atr'] <= (latest['atr_ma'] * 0.8) or not is_smart_candle(latest):
            return

        prev_body = abs(previous['close'] - previous['open'])
        prev_range = previous['high'] - previous['low']
        is_strong_prev = (prev_range > 0) and ((prev_body / prev_range) >= 0.50)

        signal = None
        if htf_bullish and latest['close'] > latest['ema_trend'] and previous['close'] > previous['open'] and is_strong_prev:
            if (previous['sma_fast'] <= previous['sma_slow']) and (latest['sma_fast'] > latest['sma_slow']):
                signal = "BUY 🟢"
            elif latest['close'] <= latest['bb_low']:
                signal = "BUY 🟢"

        elif htf_bearish and latest['close'] < latest['ema_trend'] and previous['close'] < previous['open'] and is_strong_prev:
            if (previous['sma_fast'] >= previous['sma_slow']) and (latest['sma_fast'] < latest['sma_slow']):
                signal = "SELL 🔴"
            elif latest['close'] >= latest['bb_high']:
                signal = "SELL 🔴"

        if signal:
            entry_price = latest['close']
            atr_val = latest['atr']
            target = entry_price + atr_val if "BUY" in signal else entry_price - atr_val
            stop = entry_price - atr_val if "BUY" in signal else entry_price + atr_val

            msg = (
                f"🚨 **تنبيه صفقة جديدة!**\n\n"
                f"📊 **الزوج:** {pair_name}\n"
                f"⏱️ **الفريم:** {entry_tf}\n"
                f"🎯 **الاتجاه:** {signal}\n"
                f"💵 **سعر الدخول:** `{entry_price:.5f}`\n"
                f"🎯 **الهدف:** `{target:.5f}`\n"
                f"🛑 **الوقف:** `{stop:.5f}`\n"
            )
            print(f"✅ تم العثور على إشارة لـ {pair_name}")
            send_telegram(msg)

    except Exception as e:
        print(f"❌ خطأ في فحص {pair_name}: {e}")

if __name__ == "__main__":
    print("🚀 بدء تشغيل بوت التداول الذكي بالقائمة الذهبية...")
    send_telegram("🚀 **تم تشغيل بوت التداول الذكي بنجاح بالقائمة الذهبية!**")
    
    while True:
        for symbol, config in GOLDEN_CONFIGS.items():
            check_signal(symbol, config)
            time.sleep(1)
        
        # الانتظار 300 ثانية (5 دقائق) بين دورات الفحص
        time.sleep(300)
