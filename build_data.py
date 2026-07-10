#!/usr/bin/env python3
"""build_data.py — AI関連銘柄の多様体  日次データ取得バッチ
54銘柄の株価・前日比・時価総額をyfinanceで取得し data.json を出力する。
"""
import json
import sys
import time
from datetime import datetime, timezone, timedelta, date as _date
from pathlib import Path

import pandas as pd
import yfinance as yf

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

SCRIPT_DIR = Path(__file__).parent
DATA_PATH  = SCRIPT_DIR / "data.json"

JST            = timezone(timedelta(hours=9))
MAX_RETRIES    = 5
RETRY_INTERVAL = 10  # 秒
STALE_DAYS     = 5   # 取得日付が本日からこの日数を超えると古いとみなし前回値を保持（他4サイト＋ハブと同じ作法）

# 54銘柄（ユニーク）。yfinanceティッカーは末尾に .T を付ける
STOCK_CODES = [
    # 島1 AI
    "9432", "9433", "6702", "6701", "6758", "9984",
    # 島2 半導体
    "285A", "6723", "6526",
    # 島3 製造装置
    "8035", "6920", "6857", "6146", "7735", "6525", "6315", "6323", "6254", "7751", "7731",
    # 島4 材料
    "4063", "3436", "4004", "4062", "7741", "5384", "3110", "6855", "6890",
    # 島5 電子部品
    "6981", "6976", "6762", "6971", "6479", "6997", "6779", "5344", "6787",
    # 島6 電線
    "5803", "5801", "5802",
    # 島7 パワー半導体
    "6963", "6504", "6503",
    # 島8 フィジカルAI
    "6861", "6954", "6506", "6273", "6324", "6594", "6645",
    # 島9 データセンター
    "3778", "3905", "6501",
]


def now_jst():
    return datetime.now(JST)


def jst_iso(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(JST).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def load_prev():
    if DATA_PATH.exists():
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save(data):
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _mcap_trillion(t):
    """時価総額（兆円）。取得できなければ None。"""
    # fast_info (yfinance >= 0.2.x)
    try:
        mc = t.fast_info.market_cap
        if mc and mc > 0:
            return round(float(mc) / 1e12, 4)
    except Exception:
        pass
    # 旧 API / フォールバック
    try:
        mc = t.info.get("marketCap")
        if mc and mc > 0:
            return round(float(mc) / 1e12, 4)
    except Exception:
        pass
    return None


def _quote_latest(ticker_obj):
    """
    チャートAPIメタ（quote相当）から直近約定値と時刻を返す。
    2026-07-06頃からYahooのチャートAPIが東証銘柄で「引け後〜翌営業日の反映まで」
    直近セッションの日足バーを返さなくなったため、
    日足の最終バーが古い場合のフォールバックとして使う。
    直近の history() 呼び出しのレスポンスを再利用するので追加リクエストは発生しない。
    Returns: (price: float|None, dt: datetime|None)  — dt は取引所タイムゾーン
    """
    try:
        meta    = ticker_obj.get_history_metadata()
        price   = meta.get("regularMarketPrice")
        epoch   = meta.get("regularMarketTime")
        tz_name = meta.get("exchangeTimezoneName")
        if price is None or epoch is None or tz_name is None:
            return None, None
        dt = pd.Timestamp(epoch, unit="s", tz="UTC").tz_convert(tz_name).to_pydatetime()
        return float(price), dt
    except Exception:
        return None, None


def fetch_one(code):
    """(price, change_pct, mcap_trillion, date_str) を返す。失敗時は (None, None, None, None)。"""
    ticker_str = f"{code}.T"
    for attempt in range(MAX_RETRIES):
        try:
            t    = yf.Ticker(ticker_str)
            hist = t.history(period="5d")
            if hist.empty:
                raise ValueError("empty history")
            closes = hist["Close"].dropna()
            if closes.empty:
                raise ValueError("all NaN")

            price    = round(float(closes.iloc[-1]), 2)
            date_str = str(closes.index[-1].date())
            prev     = float(closes.iloc[-2]) if len(closes) >= 2 else None

            # quoteフォールバック: 日足最終バーより新しい日付の約定があれば採用
            q_val, q_dt = _quote_latest(t)
            if (q_val is not None and q_val > 0 and q_dt is not None
                    and str(q_dt.date()) > date_str):
                print(f"  {code:5s}  [補正] 日足が{date_str}止まり → quote終値({q_dt.date()} {q_val})を採用")
                prev     = price
                price    = round(float(q_val), 2)
                date_str = str(q_dt.date())

            chg_pct = None
            if prev:
                chg_pct = round((price - prev) / abs(prev) * 100, 4)

            mcap = _mcap_trillion(t)
            return price, chg_pct, mcap, date_str

        except Exception as e:
            print(f"  {code} attempt {attempt+1}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_INTERVAL)

    return None, None, None, None


def main():
    generated_at = now_jst()
    prev         = load_prev()
    prev_stocks  = prev.get("stocks", {})

    stocks_out = {}
    any_fail = any_stale = False

    for code in STOCK_CODES:
        p0 = prev_stocks.get(code, {})
        price, chg, mcap, date = fetch_one(code)

        if price is not None:
            # 取得は成功したが日付が STALE_DAYS 超に古い → 前回値を保持（日付が古いデータを採用しない）
            age = (_date.today() - _date.fromisoformat(date)).days if date else None
            if age is not None and age > STALE_DAYS and p0.get("price") is not None:
                print(f"  {code:5s}  警告: データが{age}日前 ({date}) > STALE_DAYS({STALE_DAYS}) → 前回値保持")
                price = p0.get("price")
                chg   = p0.get("change_pct")
                mcap  = p0.get("mcap_trillion")
                date  = p0.get("date")
                status    = "stale"
                any_stale = True
            else:
                status = "ok"
                mcap_disp = f"{mcap}T" if mcap is not None else "—"
                print(f"  {code:5s}  {price:>10.1f}  {(chg or 0):+.2f}%  mcap={mcap_disp}  [{date}]")
        else:
            # 前回値でフォールバック
            price = p0.get("price")
            chg   = p0.get("change_pct")
            mcap  = p0.get("mcap_trillion")
            date  = p0.get("date")
            if price is not None:
                status     = "stale"
                any_stale  = True
                print(f"  {code:5s}  [STALE] {price}")
            else:
                status   = "failed"
                any_fail = True
                print(f"  {code:5s}  [FAILED]")

        stocks_out[code] = {
            "price":         price,
            "change_pct":    chg,
            "mcap_trillion": mcap,
            "date":          date,
            "status":        status,
        }

    overall = "partial" if (any_fail or any_stale) else "complete"
    output  = {
        "_meta": {
            "schema_version": "1.0",
            "generated_at":   jst_iso(generated_at),
            "overall_status": overall,
        },
        "stocks": stocks_out,
    }
    save(output)
    tag = "OK" if overall == "complete" else "WARN"
    print(f"[{tag}] data.json 書き出し完了  overall={overall}  {jst_iso(generated_at)}")


if __name__ == "__main__":
    main()
