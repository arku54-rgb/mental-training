#!/usr/bin/env python3
# mental-app.py
# メンタルトレーニング スマホアプリ（Flask）
# スマホから http://192.168.1.18:8891 でアクセス

from flask import Flask, request, jsonify, session
from functools import wraps
import urllib.request
import urllib.parse
import urllib.error
import ssl
import re
import secrets
import os
import json
from datetime import date, datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

OBSIDIAN_KEY = "89d0306fce02e74cb7b80e5dc801f73952ac6fa29a7715133a6a3dd78f67d1a0"
OBSIDIAN_URL = "https://localhost:27124"
PORT = int(os.environ.get("PORT", 8891))
APP_PIN = os.environ.get("APP_PIN", "4216")

# クラウドモード: 環境変数 SUPABASE_URL / SUPABASE_KEY が設定されていれば有効
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
USE_CLOUD = bool(SUPABASE_URL and SUPABASE_KEY)

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


@app.route("/api/login", methods=["POST"])
def login():
    pin = request.json.get("pin", "")
    if secrets.compare_digest(pin, APP_PIN):
        session["authenticated"] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "PINが違います"}), 401


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


def obsidian_get(path):
    encoded = urllib.parse.quote(path, safe="")
    req = urllib.request.Request(
        f"{OBSIDIAN_URL}/vault/{encoded}",
        headers={"Authorization": f"Bearer {OBSIDIAN_KEY}", "Accept": "text/markdown"},
    )
    with urllib.request.urlopen(req, context=ssl_ctx) as resp:
        return resp.read().decode("utf-8")


def obsidian_put(path, content):
    encoded = urllib.parse.quote(path, safe="")
    data = content.encode("utf-8")
    req = urllib.request.Request(
        f"{OBSIDIAN_URL}/vault/{encoded}",
        data=data,
        method="PUT",
        headers={
            "Authorization": f"Bearer {OBSIDIAN_KEY}",
            "Content-Type": "text/markdown",
        },
    )
    with urllib.request.urlopen(req, context=ssl_ctx) as resp:
        return resp.status


# ── Supabase（クラウドモード） ───────────────────────────────────────────

def _sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

def supabase_read(path):
    encoded = urllib.parse.quote(path, safe="")
    url = f"{SUPABASE_URL}/rest/v1/notes?path=eq.{encoded}&select=content"
    req = urllib.request.Request(url, headers=_sb_headers())
    with urllib.request.urlopen(req) as resp:
        rows = json.loads(resp.read())
    if not rows:
        raise FileNotFoundError(path)
    return rows[0]["content"]

def supabase_write(path, content):
    url = f"{SUPABASE_URL}/rest/v1/notes"
    payload = json.dumps({
        "path": path,
        "content": content,
        "updated_at": datetime.utcnow().isoformat(),
        "synced": False,
    }).encode()
    headers = {**_sb_headers(), "Prefer": "resolution=merge-duplicates"}
    req = urllib.request.Request(url, data=payload, method="POST", headers=headers)
    with urllib.request.urlopen(req):
        pass

def supabase_pending():
    url = f"{SUPABASE_URL}/rest/v1/notes?synced=eq.false&select=path,content"
    req = urllib.request.Request(url, headers=_sb_headers())
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def supabase_mark_synced(paths):
    for path in paths:
        encoded = urllib.parse.quote(path, safe="")
        url = f"{SUPABASE_URL}/rest/v1/notes?path=eq.{encoded}"
        payload = json.dumps({"synced": True}).encode()
        headers = {**_sb_headers(), "Prefer": "return=minimal"}
        req = urllib.request.Request(url, data=payload, method="PATCH", headers=headers)
        with urllib.request.urlopen(req):
            pass


# ── 読み書きの共通ラッパー ────────────────────────────────────────────────

def read_note(path):
    if USE_CLOUD:
        return supabase_read(path)
    return obsidian_get(path)

def write_note(path, content):
    if USE_CLOUD:
        supabase_write(path, content)
    else:
        obsidian_put(path, content)


def today_path():
    d = date.today().strftime("%Y-%m-%d")
    return f"MH/Daily/{d}.md"


def week_path():
    iso = date.today().isocalendar()
    w = f"{iso[0]}-W{iso[1]:02d}"
    return f"MH/Weekly/{w}.md"


def make_daily_template():
    d = date.today()
    date_str = d.strftime("%Y-%m-%d")
    iso = d.isocalendar()
    week_label = f"{iso[0]}-W{iso[1]:02d}"
    jp_days = ["月", "火", "水", "木", "金", "土", "日"]
    day_char = jp_days[d.weekday()]
    return f"""---
date: {date_str}
type: mental-daily
week: {week_label}
---

# メンタルトレーニング {date_str}（{day_char}）

## ☀️ 朝のルーティン（3分）

### ① セルフコンパッション（1分）

> 「今、自分はつらさを感じている。これは人間として自然なことだ。自分に優しくしていい。」

- [ ] フレーズを唱えた

### ② 横隔膜呼吸（2分）

吸う（鼻・腹膨らます）4秒 → 止める 2秒 → 吐く（口・腹へこます）6秒 × 6回

- [ ] 呼吸完了

---

## 🌙 夜の記録（3分）

### ③ 感情トリガーログ（あった場合のみ記入）

| 何があったか | とっさに思ったこと（解釈） | 身体の反応（肩・胃・顎など） |
|------------|------------------------|--------------------------|
|            |                        |                          |

### ④ 今日の良かったこと（自己承認）

>

---

*Week: [[{week_label}]] | [[MH/メンタルトレーニング]]*
"""


def ensure_daily_note():
    path = today_path()
    try:
        read_note(path)
    except (FileNotFoundError, urllib.error.HTTPError) as e:
        if isinstance(e, urllib.error.HTTPError) and e.code != 404:
            raise
        write_note(path, make_daily_template())


# ── API ────────────────────────────────────────────────────────────────

@app.route("/api/save-morning", methods=["POST"])
@login_required
def save_morning():
    try:
        data = request.json
        ensure_daily_note()
        path = today_path()
        content = read_note(path)
        if data.get("compassion"):
            content = content.replace("- [ ] フレーズを唱えた", "- [x] フレーズを唱えた")
        if data.get("breath"):
            content = content.replace("- [ ] 呼吸完了", "- [x] 呼吸完了")
        write_note(path, content)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/save-evening", methods=["POST"])
@login_required
def save_evening():
    try:
        data = request.json
        ensure_daily_note()
        path = today_path()
        content = read_note(path)

        ev = data.get("trigger_event", "").strip()
        th = data.get("trigger_thought", "").strip()
        bd = data.get("trigger_body", "").strip()
        if ev or th or bd:
            old = "|            |                        |                          |"
            new = f"| {ev} | {th} | {bd} |"
            content = content.replace(old, new, 1)

        good = data.get("good_thing", "").strip()
        if good:
            content = content.replace(
                "### ④ 今日の良かったこと（自己承認）\n\n>",
                f"### ④ 今日の良かったこと（自己承認）\n\n> {good}",
                1,
            )

        write_note(path, content)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/save-weekly", methods=["POST"])
@login_required
def save_weekly():
    try:
        data = request.json
        path = week_path()
        content = read_note(path)

        if data.get("emotion"):
            content = content.replace(
                "> 今週、怒り・緊張はどんな場面で出たか？共通するトリガーはあるか？",
                f"> {data['emotion']}",
                1,
            )
        if data.get("self_eval"):
            content = content.replace(
                "> 他者の言動に振り回された場面はあったか？そのとき何を信じていたか？",
                f"> {data['self_eval']}",
                1,
            )
        a = data.get("aerophagia", "5")
        t = data.get("tension", "5")
        content = re.sub(r"\| 呑気症 \|[^|]*\|[^|]*\|", f"| 呑気症 | {a}/10 | |", content)
        content = re.sub(r"\| 過緊張 \|[^|]*\|[^|]*\|", f"| 過緊張 | {t}/10 | |", content)

        if data.get("good_things"):
            content = content.replace(
                "## 今週の良かったこと（自己承認）\n\n1.\n2.\n3.",
                f"## 今週の良かったこと（自己承認）\n\n{data['good_things']}",
                1,
            )
        if data.get("pride_action"):
            content = content.replace(
                "今週、自分が誇れた行動・判断は？（他者の評価に関係なく、自分として正しいと思えたこと）\n>",
                f"今週、自分が誇れた行動・判断は？（他者の評価に関係なく、自分として正しいと思えたこと）\n> {data['pride_action']}",
                1,
            )
        if data.get("real_value"):
            content = content.replace(
                "今週、他者の評価に引っ張られた場面を振り返ると、本当は何を大切にしたかった？\n>",
                f"今週、他者の評価に引っ張られた場面を振り返ると、本当は何を大切にしたかった？\n> {data['real_value']}",
                1,
            )
        if data.get("focus"):
            content = content.replace(
                "## 来週の焦点（1つだけ）\n\n>",
                f"## 来週の焦点（1つだけ）\n\n> {data['focus']}",
                1,
            )

        write_note(path, content)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── クラウド同期エンドポイント（PC側スクリプトが使用） ──────────────────────

@app.route("/api/pending-sync", methods=["GET"])
@login_required
def pending_sync():
    if not USE_CLOUD:
        return jsonify([])
    try:
        return jsonify(supabase_pending())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/mark-synced", methods=["POST"])
@login_required
def mark_synced():
    paths = request.json.get("paths", [])
    try:
        supabase_mark_synced(paths)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── HTML ───────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<meta name="theme-color" content="#111827">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>メンタルトレーニング</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
/* PINロック画面 */
#pin-screen{position:fixed;inset:0;background:#0f172a;z-index:999;
  display:flex;flex-direction:column;align-items:center;justify-content:center;padding:40px}
#pin-screen.hidden{display:none}
.pin-title{font-size:20px;font-weight:700;color:#93c5fd;margin-bottom:8px}
.pin-sub{font-size:13px;color:#64748b;margin-bottom:32px}
.pin-dots{display:flex;gap:12px;margin-bottom:24px}
.pin-dot{width:14px;height:14px;border-radius:50%;border:2px solid #334155;transition:.2s}
.pin-dot.filled{background:#3b82f6;border-color:#3b82f6}
.pin-pad{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;width:220px}
.pin-key{padding:18px;border-radius:12px;border:1px solid #334155;background:#1e293b;
  color:#e2e8f0;font-size:20px;font-weight:600;cursor:pointer;text-align:center;
  transition:.15s;user-select:none}
.pin-key:active{background:#334155}
.pin-key.del{font-size:14px;color:#64748b}
.pin-err{color:#f87171;font-size:13px;margin-top:12px;height:18px}
body{font-family:-apple-system,BlinkMacSystemFont,'Hiragino Sans',sans-serif;
  background:#0f172a;color:#e2e8f0;min-height:100dvh;display:flex;flex-direction:column}
header{background:#1e293b;padding:14px 20px 10px;text-align:center;
  border-bottom:1px solid #334155;position:sticky;top:0;z-index:100}
header h1{font-size:17px;font-weight:700;color:#93c5fd}
header p{font-size:11px;color:#64748b;margin-top:2px}
.tabs{display:flex;background:#1e293b;border-bottom:1px solid #334155;
  position:sticky;top:57px;z-index:99}
.tab{flex:1;padding:10px 4px;text-align:center;font-size:11px;color:#64748b;
  cursor:pointer;border-bottom:2px solid transparent;transition:.2s}
.tab.active{color:#93c5fd;border-bottom-color:#3b82f6}
.tab-icon{font-size:18px;display:block;margin-bottom:1px}
.content{flex:1;padding:16px 14px 50px;max-width:440px;margin:0 auto;width:100%}
.panel{display:none}.panel.active{display:block}
.card{background:#1e293b;border:1px solid #334155;border-radius:14px;
  padding:16px;margin-bottom:14px}
.card-title{font-size:13px;font-weight:600;color:#93c5fd;margin-bottom:10px;
  display:flex;align-items:center;gap:6px}

/* セルフコンパッション */
.phrase{background:linear-gradient(135deg,#1e1b4b,#2e1065);
  border:1px solid #4c1d95;border-radius:12px;padding:18px;
  text-align:center;font-size:14px;line-height:1.9;color:#ddd6fe;
  font-style:italic;margin-bottom:12px}

/* 呼吸タイマー */
.breath-wrap{display:flex;flex-direction:column;align-items:center;padding:12px 0}
.circle{width:130px;height:130px;border-radius:50%;
  background:radial-gradient(circle,#312e81,#1e1b4b);
  border:2px solid #6366f1;display:flex;align-items:center;justify-content:center;
  flex-direction:column;transition:transform .6s ease,border-color .6s,background .6s;
  margin-bottom:12px}
.circle.in{transform:scale(1.28);border-color:#818cf8;background:radial-gradient(circle,#4338ca,#312e81)}
.circle.hold{transform:scale(1.28);border-color:#f59e0b;background:radial-gradient(circle,#92400e,#451a03)}
.circle.out{transform:scale(1);border-color:#34d399;background:radial-gradient(circle,#064e3b,#022c22)}
.c-label{font-size:16px;font-weight:700;color:#e2e8f0}
.c-num{font-size:26px;font-weight:700;color:#93c5fd}
.c-set{font-size:12px;color:#64748b;margin-top:8px}
.c-hint{font-size:12px;color:#64748b;margin-bottom:12px}

/* チェックボックス行 */
.chk-row{display:flex;align-items:center;gap:10px;padding:9px 0;
  border-top:1px solid #1e293b;font-size:14px}
.chk{width:22px;height:22px;border:2px solid #3b82f6;border-radius:6px;
  display:flex;align-items:center;justify-content:center;
  cursor:pointer;flex-shrink:0;transition:.2s}
.chk.on{background:#3b82f6}
.chk.on::after{content:'✓';color:#fff;font-size:13px;font-weight:700}

/* ボタン */
.btn{width:100%;padding:13px;border-radius:12px;border:none;
  font-size:14px;font-weight:700;cursor:pointer;transition:.15s;margin-top:4px}
.btn-blue{background:#3b82f6;color:#fff}.btn-blue:active{background:#2563eb}
.btn-blue:disabled{background:#1e3a5f;color:#475569;cursor:not-allowed}
.btn-green{background:#059669;color:#fff}.btn-green:active{background:#047857}
.btn-outline{background:transparent;border:1px solid #3b82f6;color:#93c5fd;margin-bottom:6px}

/* テキストエリア */
textarea{width:100%;background:#0f172a;border:1px solid #334155;border-radius:10px;
  color:#e2e8f0;padding:11px;font-size:14px;font-family:inherit;
  resize:vertical;min-height:72px;margin-top:6px}
textarea:focus{outline:none;border-color:#3b82f6}
textarea::placeholder{color:#334155}
label{font-size:12px;color:#64748b;display:block;margin-top:10px}
label:first-child{margin-top:0}

/* スライダー */
.slider-row{display:flex;align-items:center;gap:10px;margin:8px 0}
.slider-row label{min-width:68px;font-size:12px;color:#64748b;margin:0}
input[type=range]{flex:1;accent-color:#93c5fd;height:4px;
  -webkit-appearance:none;background:#334155;border-radius:2px;outline:none}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;
  width:18px;height:18px;background:#93c5fd;border-radius:50%;cursor:pointer}
.s-val{min-width:24px;text-align:right;font-size:14px;font-weight:700;color:#93c5fd}

/* グラウンディング */
.ground-row{display:flex;align-items:center;gap:10px;padding:8px 0;
  border-bottom:1px solid #1e293b;transition:.3s}
.ground-row:last-child{border-bottom:none}
.ground-row.lit .gr-item{color:#e2e8f0}
.gr-num{width:22px;height:22px;border-radius:50%;background:#1e3a5f;
  color:#93c5fd;font-size:12px;font-weight:700;display:flex;align-items:center;
  justify-content:center;flex-shrink:0}
.ground-row.lit .gr-num{background:#3b82f6}
.gr-item{font-size:14px;color:#334155}

/* ステータス */
.status{text-align:center;font-size:13px;padding:10px;border-radius:8px;
  margin-top:8px;display:none}
.status.ok{background:#052e16;color:#4ade80;display:block}
.status.ng{background:#450a0a;color:#f87171;display:block}
</style>
</head>
<body>

<!-- PINロック画面 -->
<div id="pin-screen">
  <div class="pin-title">🔒 メンタルトレーニング</div>
  <div class="pin-sub">PINを入力してください</div>
  <div class="pin-dots">
    <div class="pin-dot" id="pd0"></div>
    <div class="pin-dot" id="pd1"></div>
    <div class="pin-dot" id="pd2"></div>
    <div class="pin-dot" id="pd3"></div>
  </div>
  <div class="pin-pad">
    <div class="pin-key" onclick="pinKey('1')">1</div>
    <div class="pin-key" onclick="pinKey('2')">2</div>
    <div class="pin-key" onclick="pinKey('3')">3</div>
    <div class="pin-key" onclick="pinKey('4')">4</div>
    <div class="pin-key" onclick="pinKey('5')">5</div>
    <div class="pin-key" onclick="pinKey('6')">6</div>
    <div class="pin-key" onclick="pinKey('7')">7</div>
    <div class="pin-key" onclick="pinKey('8')">8</div>
    <div class="pin-key" onclick="pinKey('9')">9</div>
    <div class="pin-key del" onclick="pinDel()">←</div>
    <div class="pin-key" onclick="pinKey('0')">0</div>
    <div class="pin-key del" onclick="pinClear()">✕</div>
  </div>
  <div class="pin-err" id="pin-err"></div>
</div>

<header>
  <h1>🧠 メンタルトレーニング</h1>
  <p id="date-label"></p>
</header>

<div class="tabs">
  <div class="tab active" onclick="tab('morning')"><span class="tab-icon">☀️</span>朝</div>
  <div class="tab" onclick="tab('train')"><span class="tab-icon">🚃</span>帰宅</div>
  <div class="tab" onclick="tab('evening')"><span class="tab-icon">🌙</span>夜</div>
  <div class="tab" onclick="tab('weekly')"><span class="tab-icon">📋</span>週次</div>
</div>

<div class="content">

<!-- 朝 -->
<div class="panel active" id="panel-morning">
  <div class="card">
    <div class="card-title">💜 セルフコンパッション（1分）</div>
    <div class="phrase">
      「今、自分はつらさを感じている。<br>
      これは人間として自然なことだ。<br>
      自分に優しくしていい。」
    </div>
    <div class="chk-row">
      <div class="chk" id="chk-c" onclick="toggle('chk-c')"></div>
      <span>フレーズを唱えた</span>
    </div>
  </div>

  <div class="card">
    <div class="card-title">🌬️ 横隔膜呼吸（2分）</div>
    <div class="breath-wrap">
      <div class="circle" id="bcirc">
        <div class="c-label" id="blabel">準備</div>
        <div class="c-num" id="bnum">-</div>
      </div>
      <div class="c-hint">吸う 4秒 → 止める 2秒 → 吐く 6秒 × 6回</div>
      <div class="c-set" id="bset"></div>
    </div>
    <button class="btn btn-outline" id="bbtn" onclick="startBreath()">呼吸を開始</button>
    <div class="chk-row">
      <div class="chk" id="chk-b" onclick="toggle('chk-b')"></div>
      <span>呼吸完了</span>
    </div>
  </div>

  <button class="btn btn-blue" onclick="saveMorning()">朝のルーティン完了を記録</button>
  <div class="status" id="st-morning"></div>
</div>

<!-- 帰り電車 -->
<div class="panel" id="panel-train">
  <div class="card">
    <div class="card-title">🔚 ステップ1｜仕事モードをOFFにする</div>
    <div class="phrase" style="font-size:13px;line-height:2;">
      「今日の仕事は終わった。<br>
      あとは自分の時間だ。<br>
      今ここにいる自分でいい。」
    </div>
    <div class="chk-row">
      <div class="chk" id="chk-t1" onclick="toggle('chk-t1')"></div>
      <span>フレーズを読んだ</span>
    </div>
  </div>

  <div class="card">
    <div class="card-title">🌬️ ステップ2｜呼吸で緊張を流す</div>
    <div class="breath-wrap">
      <div class="circle" id="tcirc">
        <div class="c-label" id="tlabel">準備</div>
        <div class="c-num" id="tnum">-</div>
      </div>
      <div class="c-hint">吸う 4秒 → 止める 2秒 → 吐く 6秒 × 3回</div>
      <div class="c-set" id="tset"></div>
    </div>
    <button class="btn btn-outline" id="tbtn" onclick="startTrainBreath()">呼吸を開始（約40秒）</button>
    <div class="chk-row" style="margin-top:8px;">
      <div class="chk" id="chk-t2" onclick="toggle('chk-t2')"></div>
      <span>呼吸完了</span>
    </div>
  </div>

  <div class="card">
    <div class="card-title">🫁 ステップ3｜身体スキャン</div>
    <p style="font-size:13px;color:#94a3b8;line-height:1.8;margin-bottom:12px;">
      それぞれの部位を意識して、力を抜いてください。
    </p>
    <div class="chk-row">
      <div class="chk" id="chk-t3a" onclick="toggle('chk-t3a')"></div>
      <span>肩 — 力が入っていたら、息を吐きながら落とす</span>
    </div>
    <div class="chk-row">
      <div class="chk" id="chk-t3b" onclick="toggle('chk-t3b')"></div>
      <span>顎 — 食いしばっていたら、口を少し開けて緩める</span>
    </div>
    <div class="chk-row">
      <div class="chk" id="chk-t3c" onclick="toggle('chk-t3c')"></div>
      <span>胸・お腹 — 浅い呼吸になっていたら、お腹に手を置いて確認</span>
    </div>
  </div>

  <div class="card">
    <div class="card-title">👁️ ステップ4｜グラウンディング（今ここに戻る）</div>
    <p style="font-size:13px;color:#94a3b8;line-height:1.8;margin-bottom:12px;">
      今この瞬間、目に見えるものを5つ数える。<br>
      頭の中から「今ここ」の感覚に切り替える。
    </p>
    <div id="ground-items">
      <div class="ground-row" id="gr0"><span class="gr-num">1</span><span class="gr-item">―</span></div>
      <div class="ground-row" id="gr1"><span class="gr-num">2</span><span class="gr-item">―</span></div>
      <div class="ground-row" id="gr2"><span class="gr-num">3</span><span class="gr-item">―</span></div>
      <div class="ground-row" id="gr3"><span class="gr-num">4</span><span class="gr-item">―</span></div>
      <div class="ground-row" id="gr4"><span class="gr-num">5</span><span class="gr-item">―</span></div>
    </div>
    <button class="btn btn-outline" style="margin-top:10px;" onclick="startGround()">カウントを開始</button>
    <div class="chk-row" style="margin-top:8px;">
      <div class="chk" id="chk-t4" onclick="toggle('chk-t4')"></div>
      <span>5つ確認できた</span>
    </div>
  </div>
</div>

<!-- 夜 -->
<div class="panel" id="panel-evening">
  <div class="card">
    <div class="card-title">⚡ 感情トリガーログ（任意）</div>
    <label>怒り・緊張が出た場面</label>
    <textarea id="ev" placeholder="何があったか…（なければスキップ）" rows="2"></textarea>
    <label>とっさに思ったこと（解釈）</label>
    <textarea id="th" placeholder="どう受け取ったか…" rows="2"></textarea>
    <label>身体の反応（肩・胃・顎など）</label>
    <textarea id="bd" placeholder="どこに出たか…" rows="2"></textarea>
  </div>
  <div class="card">
    <div class="card-title">✨ 今日の良かったこと（自己承認）</div>
    <textarea id="gd" placeholder="小さいことでOK。自分を認めるひとことを。" rows="3"></textarea>
  </div>
  <button class="btn btn-green" onclick="saveEvening()">夜の記録を保存</button>
  <div class="status" id="st-evening"></div>
</div>

<!-- 週次 -->
<div class="panel" id="panel-weekly">
  <div class="card">
    <div class="card-title">⚡ 感情パターン</div>
    <textarea id="w-em" placeholder="今週、怒り・緊張はどんな場面で出たか？共通のトリガーは？" rows="3"></textarea>
  </div>
  <div class="card">
    <div class="card-title">🪞 自己評価・他者評価</div>
    <textarea id="w-se" placeholder="他者の言動に振り回された場面は？そのとき何を信じていたか？" rows="3"></textarea>
  </div>
  <div class="card">
    <div class="card-title">🫁 身体状態</div>
    <div class="slider-row">
      <label>呑気症</label>
      <input type="range" id="w-ae" min="1" max="10" value="5" oninput="sv(this,'sv-ae')">
      <span class="s-val" id="sv-ae">5</span>
    </div>
    <div class="slider-row">
      <label>過緊張</label>
      <input type="range" id="w-te" min="1" max="10" value="5" oninput="sv(this,'sv-te')">
      <span class="s-val" id="sv-te">5</span>
    </div>
  </div>
  <div class="card">
    <div class="card-title">🌟 今週の良かったこと</div>
    <textarea id="w-gd" placeholder="1. &#10;2. &#10;3. " rows="4"></textarea>
  </div>
  <div class="card">
    <div class="card-title">🧭 自分の軸チェック</div>
    <label>今週、自分が誇れた行動・判断は？（他者の評価に関係なく）</label>
    <textarea id="w-pr" placeholder="結果ではなく、自分として正しいと思えた行動や判断を…" rows="3"></textarea>
    <label>他者の評価に引っ張られた場面を振り返ると、本当は何を大切にしたかった？</label>
    <textarea id="w-rv" placeholder="本当は何を優先したかった？どんな自分でいたかった？" rows="3"></textarea>
  </div>
  <div class="card">
    <div class="card-title">🎯 来週の焦点（1つだけ）</div>
    <textarea id="w-fo" placeholder="来週、特に意識したいこと…" rows="2"></textarea>
  </div>
  <button class="btn btn-blue" onclick="saveWeekly()">週次振り返りを保存</button>
  <div class="status" id="st-weekly"></div>
</div>

</div>

<script>
// PINロック
let pinBuf = '';
function pinKey(d) {
  if(pinBuf.length >= 4) return;
  pinBuf += d;
  updateDots();
  if(pinBuf.length === 4) submitPin();
}
function pinDel(){ pinBuf=pinBuf.slice(0,-1); updateDots(); }
function pinClear(){ pinBuf=''; updateDots(); }
function updateDots(){
  for(let i=0;i<4;i++) document.getElementById('pd'+i).classList.toggle('filled',i<pinBuf.length);
}
async function submitPin(){
  try{
    const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pin:pinBuf})});
    const j=await r.json();
    if(j.ok){ document.getElementById('pin-screen').classList.add('hidden'); }
    else{ document.getElementById('pin-err').textContent='PINが違います'; pinBuf=''; updateDots(); setTimeout(()=>document.getElementById('pin-err').textContent='',2000); }
  }catch(e){ pinBuf=''; updateDots(); }
}
// セッション確認（リロード時）
fetch('/api/save-morning',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(2000)})
  .then(r=>{ if(r.status!==401) document.getElementById('pin-screen').classList.add('hidden'); })
  .catch(()=>{});

// 今日の日付表示
const d = new Date();
document.getElementById('date-label').textContent =
  d.toLocaleDateString('ja-JP',{year:'numeric',month:'long',day:'numeric',weekday:'short'});

// タブ切り替え
function tab(name) {
  ['morning','train','evening','weekly'].forEach((n,i) => {
    document.querySelectorAll('.tab')[i].classList.toggle('active', n===name);
    document.getElementById('panel-'+n).classList.toggle('active', n===name);
  });
}

// チェックボックス
function toggle(id) {
  document.getElementById(id).classList.toggle('on');
}

// 呼吸タイマー
const PH = [{n:'吸う',s:4,c:'in'},{n:'止める',s:2,c:'hold'},{n:'吐く',s:6,c:'out'}];
let bTimer=null, bPhase=0, bSec=0, bSet=0;

function startBreath() {
  if(bTimer){clearInterval(bTimer);bTimer=null}
  bPhase=0;bSec=0;bSet=0;
  const btn=document.getElementById('bbtn');
  btn.textContent='実施中…';btn.disabled=true;
  step();bTimer=setInterval(step,1000);
}

function step() {
  const ph=PH[bPhase];
  const circ=document.getElementById('bcirc');
  circ.className='circle '+ph.c;
  document.getElementById('blabel').textContent=ph.n;
  document.getElementById('bnum').textContent=ph.s-bSec;
  document.getElementById('bset').textContent=`${bSet+1} / 6 セット`;
  if(++bSec>=ph.s){
    bSec=0;
    if(++bPhase>=PH.length){bPhase=0;
      if(++bSet>=6){
        clearInterval(bTimer);bTimer=null;
        circ.className='circle';
        document.getElementById('blabel').textContent='完了！';
        document.getElementById('bnum').textContent='✓';
        document.getElementById('bset').textContent='6セット完了';
        const btn=document.getElementById('bbtn');
        btn.textContent='呼吸を開始';btn.disabled=false;
        document.getElementById('chk-b').classList.add('on');
      }
    }
  }
}

// 帰り電車 呼吸タイマー（3セット）
let tTimer=null, tPhase=0, tSec=0, tSet=0;
function startTrainBreath(){
  if(tTimer){clearInterval(tTimer);tTimer=null}
  tPhase=0;tSec=0;tSet=0;
  const btn=document.getElementById('tbtn');
  btn.textContent='実施中…';btn.disabled=true;
  tstep();tTimer=setInterval(tstep,1000);
}
function tstep(){
  const ph=PH[tPhase];
  const circ=document.getElementById('tcirc');
  circ.className='circle '+ph.c;
  document.getElementById('tlabel').textContent=ph.n;
  document.getElementById('tnum').textContent=ph.s-tSec;
  document.getElementById('tset').textContent=`${tSet+1} / 3 セット`;
  if(++tSec>=ph.s){
    tSec=0;
    if(++tPhase>=PH.length){tPhase=0;
      if(++tSet>=3){
        clearInterval(tTimer);tTimer=null;
        circ.className='circle';
        document.getElementById('tlabel').textContent='完了！';
        document.getElementById('tnum').textContent='✓';
        document.getElementById('tset').textContent='3セット完了';
        const btn=document.getElementById('tbtn');
        btn.textContent='呼吸を開始（約40秒）';btn.disabled=false;
        document.getElementById('chk-t2').classList.add('on');
      }
    }
  }
}

// グラウンディング
const GROUND_PROMPTS=['窓の外に見えるもの','車内で目に入るもの','自分の手元にあるもの','床や座席など触れているもの','遠くに見えるもの'];
let gIdx=0,gTimer=null;
function startGround(){
  gIdx=0;
  for(let i=0;i<5;i++){
    const row=document.getElementById('gr'+i);
    row.classList.remove('lit');
    row.querySelector('.gr-item').textContent='―';
  }
  if(gTimer)clearInterval(gTimer);
  gTimer=setInterval(()=>{
    if(gIdx>=5){clearInterval(gTimer);document.getElementById('chk-t4').classList.add('on');return}
    const row=document.getElementById('gr'+gIdx);
    row.querySelector('.gr-item').textContent=GROUND_PROMPTS[gIdx];
    row.classList.add('lit');
    gIdx++;
  },1200);
}

function sv(el,id){document.getElementById(id).textContent=el.value}

// API 呼び出し
async function post(url,data){
  const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  return r.json();
}

function showSt(id,msg,ok){
  const el=document.getElementById(id);
  el.textContent=msg;el.className='status '+(ok?'ok':'ng');
  setTimeout(()=>el.className='status',5000);
}

async function saveMorning(){
  try{
    const r=await post('/api/save-morning',{
      compassion:document.getElementById('chk-c').classList.contains('on'),
      breath:document.getElementById('chk-b').classList.contains('on')
    });
    showSt('st-morning',r.ok?'✓ 朝のルーティンを記録しました':'エラー: '+r.error,r.ok);
  }catch(e){showSt('st-morning','サーバーに接続できません',false)}
}

async function saveEvening(){
  try{
    const r=await post('/api/save-evening',{
      trigger_event:document.getElementById('ev').value,
      trigger_thought:document.getElementById('th').value,
      trigger_body:document.getElementById('bd').value,
      good_thing:document.getElementById('gd').value
    });
    showSt('st-evening',r.ok?'✓ 夜の記録を保存しました':'エラー: '+r.error,r.ok);
    if(r.ok)['ev','th','bd','gd'].forEach(id=>document.getElementById(id).value='');
  }catch(e){showSt('st-evening','サーバーに接続できません',false)}
}

async function saveWeekly(){
  try{
    const r=await post('/api/save-weekly',{
      emotion:document.getElementById('w-em').value,
      self_eval:document.getElementById('w-se').value,
      aerophagia:document.getElementById('w-ae').value,
      tension:document.getElementById('w-te').value,
      good_things:document.getElementById('w-gd').value,
      pride_action:document.getElementById('w-pr').value,
      real_value:document.getElementById('w-rv').value,
      focus:document.getElementById('w-fo').value
    });
    showSt('st-weekly',r.ok?'✓ 週次振り返りを保存しました':'エラー: '+r.error,r.ok);
  }catch(e){showSt('st-weekly','サーバーに接続できません',false)}
}
</script>
</body>
</html>"""


@app.route("/")
def index():
    return HTML


if __name__ == "__main__":
    mode = "クラウド（Supabase）" if USE_CLOUD else "ローカル（Obsidian REST API）"
    print(f"起動中 [{mode}]: http://0.0.0.0:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
