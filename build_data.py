#!/usr/bin/env python3
"""build_data.py — AI関連銘柄の多様体  日次データ取得バッチ
54銘柄の株価・前日比・時価総額をyfinanceで取得し data.json を出力する。
"""
import json
import re
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
INDEX_PATH = SCRIPT_DIR / "index.html"
DESC_PATH  = SCRIPT_DIR / "ai_manifold_desc.json"

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


# =========================================================================
# 静的HTML焼き込み用データ(index.html内 ISLANDS/STOCKS のJS定数と同一。
# renderList()/renderTodaySummary() をPython側で再現するためのミラー)
# =========================================================================
ISLANDS = {
    "ai":    "AI・LLM／国内テック",
    "semi":  "半導体",
    "equip": "半導体製造装置",
    "mat":   "半導体材料",
    "parts": "電子部品",
    "cable": "電線・ケーブル",
    "power": "パワー半導体",
    "phys":  "フィジカルAI",
    "dc":    "データセンター",
}

# 島の表示順(index.html の ISLANDS オブジェクトの列挙順と一致させる)
ISLAND_ORDER = ["ai", "semi", "equip", "mat", "parts", "cable", "power", "phys", "dc"]

STOCKS = [
    {"c": "9432", "n": "NTT",                "home": "ai",  "also": ["dc"]},
    {"c": "9433", "n": "KDDI",               "home": "ai",  "also": ["dc"]},
    {"c": "6702", "n": "富士通",              "home": "ai"},
    {"c": "6701", "n": "NEC",                "home": "ai",  "also": ["semi"]},
    {"c": "6758", "n": "ソニーG",             "home": "ai",  "also": ["semi"]},
    {"c": "9984", "n": "SBG",                "home": "ai",  "also": ["semi"]},
    {"c": "285A", "n": "キオクシア",          "home": "semi"},
    {"c": "6723", "n": "ルネサス",            "home": "semi"},
    {"c": "6526", "n": "ソシオネクス",        "home": "semi"},
    {"c": "8035", "n": "東エレク",            "home": "equip"},
    {"c": "6920", "n": "レーザーテック",      "home": "equip"},
    {"c": "6857", "n": "アドバンテスト",      "home": "equip"},
    {"c": "6146", "n": "ディスコ",            "home": "equip"},
    {"c": "7735", "n": "SCREEN",             "home": "equip"},
    {"c": "6525", "n": "コクサイ",            "home": "equip"},
    {"c": "6315", "n": "TOWA",               "home": "equip"},
    {"c": "6323", "n": "ローツェ",            "home": "equip"},
    {"c": "6254", "n": "野村マイクロ",        "home": "equip"},
    {"c": "7751", "n": "キヤノン",            "home": "equip"},
    {"c": "7731", "n": "ニコン",              "home": "equip"},
    {"c": "4063", "n": "信越化学",            "home": "mat"},
    {"c": "3436", "n": "SUMCO",              "home": "mat"},
    {"c": "4004", "n": "レゾナック",          "home": "mat", "also": ["parts"]},
    {"c": "4062", "n": "イビデン",            "home": "mat", "also": ["parts"]},
    {"c": "7741", "n": "HOYA",               "home": "mat"},
    {"c": "5384", "n": "フジミインコ",        "home": "mat"},
    {"c": "3110", "n": "日東紡",              "home": "mat", "also": ["parts"]},
    {"c": "6855", "n": "日本電子材料",        "home": "mat"},
    {"c": "6890", "n": "フェローテック",      "home": "mat"},
    {"c": "6981", "n": "村田製作所",          "home": "parts"},
    {"c": "6976", "n": "太陽誘電",            "home": "parts"},
    {"c": "6762", "n": "TDK",                "home": "parts"},
    {"c": "6971", "n": "京セラ",              "home": "parts", "also": ["semi"]},
    {"c": "6479", "n": "ミネベアミツミ",      "home": "parts", "also": ["phys"]},
    {"c": "6997", "n": "日本ケミコン",        "home": "parts"},
    {"c": "6779", "n": "日本電波工業",        "home": "parts"},
    {"c": "5344", "n": "MARUWA",             "home": "parts", "also": ["mat"]},
    {"c": "6787", "n": "メイコー",            "home": "parts"},
    {"c": "5803", "n": "フジクラ",            "home": "cable"},
    {"c": "5801", "n": "古河電工",            "home": "cable"},
    {"c": "5802", "n": "住友電工",            "home": "cable"},
    {"c": "6963", "n": "ローム",              "home": "power", "also": ["semi"]},
    {"c": "6504", "n": "富士電機",            "home": "power"},
    {"c": "6503", "n": "三菱電機",            "home": "power", "also": ["phys"]},
    {"c": "6861", "n": "キーエンス",          "home": "phys"},
    {"c": "6954", "n": "ファナック",          "home": "phys"},
    {"c": "6506", "n": "安川電機",            "home": "phys"},
    {"c": "6273", "n": "SMC",                "home": "phys"},
    {"c": "6324", "n": "ハーモニック",        "home": "phys"},
    {"c": "6594", "n": "ニデック",            "home": "phys", "also": ["dc"]},
    {"c": "6645", "n": "オムロン",            "home": "phys", "also": ["parts"]},
    {"c": "3778", "n": "サクラインターネット", "home": "dc"},
    {"c": "3905", "n": "データセクション",    "home": "dc", "also": ["ai"]},
    {"c": "6501", "n": "日立",                "home": "dc", "also": ["ai"]},
]

_DESC = json.loads(DESC_PATH.read_text(encoding="utf-8")) if DESC_PATH.exists() else {}


def _esc(s) -> str:
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _replace_between(text: str, start: str, end: str, inner: str) -> str:
    pattern = re.escape(start) + r".*?" + re.escape(end)
    if not re.search(pattern, text, flags=re.DOTALL):
        print(f"[bake警告] マーカーが見つかりません: {start}")
        return text
    return re.sub(pattern, lambda _: start + inner + end, text, count=1, flags=re.DOTALL)


def _replace_by_id(content: str, elem_id: str, new_inner: str) -> str:
    pattern = re.compile(r'(id="' + re.escape(elem_id) + r'"[^>]*>)[^<]*')
    if not pattern.search(content):
        print(f"[bake警告] id={elem_id} が見つかりません")
        return content
    return pattern.sub(lambda m: m.group(1) + new_inner, content, count=1)


def _mover_html(code, chg) -> str:
    """renderTodaySummary()(index.html内JS)の mover() と同一。"""
    if code is None or chg is None:
        return "—"
    name = next((s["n"] for s in STOCKS if s["c"] == code), code)
    mark = "▲" if chg > 0 else "▼" if chg < 0 else "–"
    cls = "up" if chg > 0 else "down" if chg < 0 else "flat"
    return f'{code} {name} <span class="{cls}">{mark}{abs(chg):.2f}%</span>'


def _build_summary_html(stocks_out: dict) -> str:
    """renderTodaySummary()(index.html内JS)と同一構造の静的HTML。"""
    up = down = 0
    top_code = top_chg = None
    bot_code = bot_chg = None
    for s in STOCKS:
        d = stocks_out.get(s["c"]) or {}
        if d.get("status") == "failed":
            continue
        chg = d.get("change_pct")
        if chg is None:
            continue
        if chg > 0:
            up += 1
        elif chg < 0:
            down += 1
        if top_chg is None or chg > top_chg:
            top_chg, top_code = chg, s["c"]
        if bot_chg is None or chg < bot_chg:
            bot_chg, bot_code = chg, s["c"]

    return f"""<div class="ts-card">
    <span><b class="up">{up}</b>銘柄が前日比上昇 ／ <b class="down">{down}</b>銘柄が前日比下落</span>
    <span>最高上昇 <b>{_mover_html(top_code, top_chg)}</b></span>
    <span>最大下落 <b>{_mover_html(bot_code, bot_chg)}</b></span>
  </div>"""


def _build_list_html(stocks_out: dict) -> str:
    """renderList()(index.html内JS)と同一構造の静的HTML。"""
    parts = [
        '<div class="lead"><p class="lead-h">地図の読み方</p><ul>'
        '<li><b>島（円）</b> … AIサプライチェーン上の9つのセクター。円の中の銘柄数で大きさが変わります。</li>'
        '<li><b>ノード（円の中の点）</b> … 個別銘柄。大きさは時価総額、色は前日比（緑＝上昇、赤＝下落）を表します。</li>'
        '<li><b>矢印（島と島を結ぶ線）</b> … セクター間の取引の流れ。たとえば「半導体材料 → 半導体 → データセンター → AI／LLM」のように、川上から川下へと向かいます。</li>'
        '<li><b>複数の島にまたがる銘柄</b> … 事業が複数セクターにわたる企業は、該当する島の両方に表示されます。</li>'
        '</ul><p>島をクリックすると、その島に属する銘柄の内部構造が開きます。</p></div>'
    ]
    for isl_id in ISLAND_ORDER:
        members = [s for s in STOCKS if s["home"] == isl_id]
        parts.append(
            f'<div class="sec"><div class="sec-h"><h2>{ISLANDS[isl_id]}</h2>'
            f'<span class="cnt">{len(members)}銘柄</span></div>'
        )
        for s in members:
            d = stocks_out.get(s["c"]) or {}
            price = d.get("price")
            chg = d.get("change_pct") or 0
            fresh = d.get("status") == "ok"
            price_disp = f"{round(price):,}" if price is not None else "—"
            sign = "+" if chg > 0 else ""
            color = "var(--up)" if chg > 0 else "var(--down)" if chg < -0.05 else "var(--flat)"
            arrow = "▲" if chg > 0 else "▼" if chg < -0.05 else "–"
            st = '<span class="st" title="正常更新"></span>' if fresh else ""
            also = s.get("also") or []
            cross = f' <span class="x">※{"・".join(ISLANDS[o] for o in also)}にも関連</span>' if also else ""
            desc = _DESC.get(s["c"], "")
            parts.append(
                f'<div class="row">'
                f'<span class="cd">{s["c"]}</span>'
                f'<span class="nm">{_esc(s["n"])}</span>'
                f'<span class="pr">{price_disp}{st}</span>'
                f'<span class="chg" style="color:{color}">{arrow}{sign}{chg:.2f}%</span>'
                f'<span class="ds">{desc}{cross}</span>'
                f'</div>'
            )
        parts.append("</div>")
    return "\n".join(parts)


def bake_index_html(output: dict, index_path: Path) -> None:
    if not index_path.exists():
        print(f"[bake警告] {index_path} が見つかりません。スキップ。")
        return

    content = index_path.read_text(encoding="utf-8")
    stocks_out = output.get("stocks", {})
    meta = output.get("_meta", {})

    content = _replace_between(content, "<!--SUMMARY_START-->", "<!--SUMMARY_END-->",
                                "\n" + _build_summary_html(stocks_out) + "\n")
    content = _replace_between(content, "<!--STOCK_LIST_START-->", "<!--STOCK_LIST_END-->",
                                "\n" + _build_list_html(stocks_out) + "\n")

    gen_at = meta.get("generated_at")
    if gen_at:
        try:
            dt = datetime.fromisoformat(gen_at).astimezone(JST)
            gen_str = dt.strftime("%Y/%m/%d %H:%M") + " JST"
        except Exception:
            gen_str = gen_at
        content = _replace_by_id(content, "ph-generated", gen_str)

    index_path.write_text(content, encoding="utf-8")
    print("[bake] index.html 焼き込み完了")


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
    bake_index_html(output, INDEX_PATH)
    tag = "OK" if overall == "complete" else "WARN"
    print(f"[{tag}] data.json 書き出し完了  overall={overall}  {jst_iso(generated_at)}")


if __name__ == "__main__":
    main()
