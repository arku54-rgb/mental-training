#!/usr/bin/env python3
# mental-app.py

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
from datetime import date, datetime, timedelta

try:
    import firebase_admin
    from firebase_admin import credentials, firestore as fstore
    _FIREBASE_AVAILABLE = True
except ImportError:
    _FIREBASE_AVAILABLE = False

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

OBSIDIAN_KEY = "89d0306fce02e74cb7b80e5dc801f73952ac6fa29a7715133a6a3dd78f67d1a0"
OBSIDIAN_URL = "https://localhost:27124"
PORT = int(os.environ.get("PORT", 8891))
APP_PIN = os.environ.get("APP_PIN", "4216")

FIREBASE_SA = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "")
USE_CLOUD = bool(FIREBASE_SA and _FIREBASE_AVAILABLE)

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

_fb_db = None

def _get_db():
    global _fb_db
    if _fb_db is None:
        sa = json.loads(FIREBASE_SA)
        cred = credentials.Certificate(sa)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        _fb_db = fstore.client()
    return _fb_db

def _doc_id(path):
    return path.replace("/", "--")


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
        headers={"Authorization": f"Bearer {OBSIDIAN_KEY}", "Content-Type": "text/markdown"},
    )
    with urllib.request.urlopen(req, context=ssl_ctx) as resp:
        return resp.status


def firebase_read(path):
    doc = _get_db().collection("notes").document(_doc_id(path)).get()
    if not doc.exists:
        raise FileNotFoundError(path)
    return doc.to_dict()["content"]

def firebase_write(path, content):
    _get_db().collection("notes").document(_doc_id(path)).set({
        "path": path,
        "content": content,
        "synced": False,
        "updated_at": fstore.SERVER_TIMESTAMP,
    })

def firebase_pending():
    docs = _get_db().collection("notes").where("synced", "==", False).stream()
    return [{"path": d.to_dict()["path"], "content": d.to_dict()["content"]} for d in docs]

def firebase_mark_synced(paths):
    db = _get_db()
    for path in paths:
        db.collection("notes").document(_doc_id(path)).update({"synced": True})


def read_note(path):
    return firebase_read(path) if USE_CLOUD else obsidian_get(path)

def write_note(path, content):
    if USE_CLOUD: firebase_write(path, content)
    else: obsidian_put(path, content)


def today_path():
    return f"MH/Daily/{date.today().strftime('%Y-%m-%d')}.md"

def week_path():
    iso = date.today().isocalendar()
    return f"MH/Weekly/{iso[0]}-W{iso[1]:02d}.md"


def make_daily_template():
    d = date.today()
    date_str = d.strftime("%Y-%m-%d")
    iso = d.isocalendar()
    week_label = f"{iso[0]}-W{iso[1]:02d}"
    day_char = ["月","火","水","木","金","土","日"][d.weekday()]
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


def make_weekly_template():
    d = date.today()
    iso = d.isocalendar()
    year, wn = iso[0], iso[1]
    week_label = f"{year}-W{wn:02d}"
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    date_range = f"{monday.month}/{monday.day}〜{sunday.month}/{sunday.day}"
    prev_y, prev_w = (year, wn-1) if wn > 1 else (year-1, 53)
    next_y, next_w = (year, wn+1) if wn < 53 else (year+1, 1)
    daily_links = " | ".join(
        f"[[MH/Daily/{(monday + timedelta(days=i)).strftime('%Y-%m-%d')}]]"
        for i in range(7)
    )
    return f"""---
date: {d.strftime("%Y-%m-%d")}
type: mental-weekly
week: {week_label}
---

# 週次振り返り {week_label}（{date_range}）

## 今週の日次ログ

{daily_links}

---

## 感情パターン振り返り

> 今週、怒り・緊張はどんな場面で出たか？共通するトリガーはあるか？

### 感情トリガー集計

| 出来事 | 解釈パターン（とっさに思ったこと） | 頻度 |
|--------|--------------------------------|------|
|        |                                |      |

---

## 自己評価・他者評価チェック

> 他者の言動に振り回された場面はあったか？そのとき何を信じていたか？

---

## 身体状態

| 指標 | 今週 (/10) | 先週比 |
|------|-----------|--------|
| 呑気症 |           | ±      |
| 過緊張 |           | ±      |
| 全体的な緊張感 |    | ±      |

---

## 今週の良かったこと（自己承認）

1.
2.
3.

---

## 🧭 自分の軸チェック

今週、自分が誇れた行動・判断は？（他者の評価に関係なく、自分として正しいと思えたこと）
>

今週、他者の評価に引っ張られた場面を振り返ると、本当は何を大切にしたかった？
>

---

## 🔍 今週の解釈パターン（自動分析）

（今週の記録が不足しているため分析できませんでした。日次ログに感情トリガーを記録すると次回から分析が行われます）

---

## 来週の焦点（1つだけ）

>

---

*[[{prev_y}-W{prev_w:02d}]] ← {week_label} → [[{next_y}-W{next_w:02d}]] | [[MH/メンタルトレーニング]]*
"""


def ensure_daily_note():
    path = today_path()
    try:
        read_note(path)
    except (FileNotFoundError, urllib.error.HTTPError) as e:
        if isinstance(e, urllib.error.HTTPError) and e.code != 404:
            raise
        write_note(path, make_daily_template())


def ensure_weekly_note():
    path = week_path()
    try:
        read_note(path)
    except (FileNotFoundError, urllib.error.HTTPError) as e:
        if isinstance(e, urllib.error.HTTPError) and e.code != 404:
            raise
        write_note(path, make_weekly_template())


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
                f"### ④ 今日の良かったこと（自己承認）\n\n> {good}", 1,
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
        ensure_weekly_note()
        path = week_path()
        content = read_note(path)

        if data.get("emotion"):
            content = content.replace(
                "> 今週、怒り・緊張はどんな場面で出たか？共通するトリガーはあるか？",
                f"> {data['emotion']}", 1,
            )
        if data.get("self_eval"):
            content = content.replace(
                "> 他者の言動に振り回された場面はあったか？そのとき何を信じていたか？",
                f"> {data['self_eval']}", 1,
            )

        a = data.get("aerophagia", "5")
        t = data.get("tension", "5")
        g = data.get("general_tension", "5")
        content = re.sub(r"\| 呑気症 \|[^|]*\|[^|]*\|", f"| 呑気症 | {a}/10 | |", content)
        content = re.sub(r"\| 過緊張 \|[^|]*\|[^|]*\|", f"| 過緊張 | {t}/10 | |", content)
        content = re.sub(r"\| 全体的な緊張感 \|[^|]*\|[^|]*\|", f"| 全体的な緊張感 | {g}/10 | |", content)

        if data.get("good_things"):
            content = content.replace(
                "## 今週の良かったこと（自己承認）\n\n1.\n2.\n3.",
                f"## 今週の良かったこと（自己承認）\n\n{data['good_things']}", 1,
            )
        if data.get("pride_action"):
            content = content.replace(
                "今週、自分が誇れた行動・判断は？（他者の評価に関係なく、自分として正しいと思えたこと）\n>",
                f"今週、自分が誇れた行動・判断は？（他者の評価に関係なく、自分として正しいと思えたこと）\n> {data['pride_action']}", 1,
            )
        if data.get("real_value"):
            content = content.replace(
                "今週、他者の評価に引っ張られた場面を振り返ると、本当は何を大切にしたかった？\n>",
                f"今週、他者の評価に引っ張られた場面を振り返ると、本当は何を大切にしたかった？\n> {data['real_value']}", 1,
            )
        if data.get("focus"):
            content = content.replace(
                "## 来週の焦点（1つだけ）\n\n>",
                f"## 来週の焦点（1つだけ）\n\n> {data['focus']}", 1,
            )

        write_note(path, content)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/pending-sync", methods=["GET"])
@login_required
def pending_sync():
    if not USE_CLOUD:
        return jsonify([])
    try:
        return jsonify(firebase_pending())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/mark-synced", methods=["POST"])
@login_required
def mark_synced():
    paths = request.json.get("paths", [])
    try:
        firebase_mark_synced(paths)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<meta name="theme-color" content="#0f172a">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>メンタルトレーニング</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0f172a;--surface:#1e293b;--border:#334155;
  --primary:#6366f1;--pl:#818cf8;--pdim:rgba(99,102,241,.15);
  --text:#f1f5f9;--muted:#94a3b8;
  --ok:#10b981;--ng:#ef4444;--warn:#f59e0b;
}
html,body{height:100%;background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,'Hiragino Sans','Noto Sans JP',sans-serif;
  -webkit-tap-highlight-color:transparent}
#app{display:flex;flex-direction:column;height:100dvh;max-width:480px;margin:0 auto}
.hdr{background:var(--surface);border-bottom:1px solid var(--border);
  padding:12px 16px;text-align:center;flex-shrink:0}
.hdr-title{font-size:16px;font-weight:700;color:var(--pl)}
.hdr-date{font-size:12px;color:var(--muted);margin-top:2px}
main{flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch}
.panel{display:none;padding:14px 14px 28px}
.panel.active{display:block}
.bnav{display:flex;background:var(--surface);border-top:1px solid var(--border);
  padding-bottom:env(safe-area-inset-bottom);flex-shrink:0}
.ni{flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;
  padding:10px 4px;background:none;border:none;color:var(--muted);
  font-size:10px;cursor:pointer;font-family:inherit}
.ni .ico{font-size:22px;line-height:1}
.ni.active{color:var(--pl)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:16px;
  padding:16px;margin-bottom:12px}
.ct{font-size:13px;font-weight:600;color:var(--pl);margin-bottom:12px;
  display:flex;align-items:center;gap:6px}
.phrase{background:linear-gradient(135deg,#1e1b4b,#2e1065);border:1px solid #4c1d95;
  border-radius:12px;padding:16px;text-align:center;font-size:14px;line-height:2;
  color:#ddd6fe;font-style:italic;margin-bottom:12px}
.cr{display:flex;align-items:center;gap:12px;padding:10px 0;font-size:14px;
  border-top:1px solid var(--border)}
.cr:first-of-type{border-top:none}
.cb{width:24px;height:24px;border:2px solid var(--primary);border-radius:6px;
  display:flex;align-items:center;justify-content:center;cursor:pointer;
  flex-shrink:0;transition:.2s}
.cb.on{background:var(--primary)}
.cb.on::after{content:'✓';color:#fff;font-size:14px;font-weight:700}
.bwrap{display:flex;flex-direction:column;align-items:center;padding:14px 0 6px}
.bcircle{width:140px;height:140px;border-radius:50%;
  background:radial-gradient(circle,#312e81,#1e1b4b);
  border:2px solid var(--primary);display:flex;flex-direction:column;
  align-items:center;justify-content:center;
  transition:transform .8s cubic-bezier(.4,0,.2,1),border-color .6s,background .6s;
  margin-bottom:10px}
.bcircle.in{transform:scale(1.3);border-color:#818cf8;
  background:radial-gradient(circle,#4338ca,#312e81)}
.bcircle.hold{transform:scale(1.3);border-color:var(--warn);
  background:radial-gradient(circle,#92400e,#451a03)}
.bcircle.out{transform:scale(1);border-color:#34d399;
  background:radial-gradient(circle,#064e3b,#022c22)}
.bph{font-size:15px;font-weight:600;color:var(--text)}
.bct{font-size:32px;font-weight:700;color:var(--pl);margin-top:4px}
.bdots{display:flex;gap:6px;margin-bottom:8px}
.bdot{width:8px;height:8px;border-radius:50%;background:var(--border);transition:.3s}
.bdot.done{background:var(--ok)}.bdot.cur{background:var(--pl)}
.bsets{font-size:12px;color:var(--muted)}
.bhint{font-size:12px;color:var(--muted);text-align:center;margin-bottom:10px}
.gi{display:flex;align-items:center;gap:12px;padding:10px 0;
  border-bottom:1px solid var(--border);transition:.4s}
.gi:last-child{border-bottom:none}
.gn{width:26px;height:26px;border-radius:50%;background:var(--border);
  color:var(--muted);font-size:12px;font-weight:700;display:flex;
  align-items:center;justify-content:center;flex-shrink:0;transition:.4s}
.gi.lit .gn{background:var(--primary);color:#fff}
.gt{font-size:14px;color:var(--muted);transition:.4s}
.gi.lit .gt{color:var(--text)}
.btn{width:100%;padding:14px;border-radius:12px;border:none;font-size:14px;
  font-weight:700;cursor:pointer;transition:.15s;margin-top:4px;font-family:inherit}
.bp{background:var(--primary);color:#fff}.bp:active{background:#4f46e5}
.bp:disabled{background:#1e2d5a;color:#475569;cursor:not-allowed}
.bs{background:var(--ok);color:#fff}.bs:active{background:#059669}
.bo{background:transparent;border:1px solid var(--primary);color:var(--pl);margin-bottom:8px}
.bo:active{background:var(--pdim)}.bo:disabled{border-color:var(--border);color:var(--muted)}
.fl{font-size:12px;color:var(--muted);display:block;margin-top:10px;margin-bottom:4px}
.fl:first-child{margin-top:0}
textarea{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:10px;
  color:var(--text);padding:10px 12px;font-size:14px;font-family:inherit;
  resize:vertical;min-height:72px;line-height:1.6}
textarea:focus{outline:none;border-color:var(--primary)}
textarea::placeholder{color:#334155}
.sr{display:flex;align-items:center;gap:10px;margin:10px 0}
.sl{font-size:12px;color:var(--muted);min-width:72px}
input[type=range]{flex:1;accent-color:var(--pl);height:4px;
  -webkit-appearance:none;background:var(--border);border-radius:2px;outline:none}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:20px;height:20px;
  background:var(--pl);border-radius:50%;cursor:pointer}
.sv{min-width:28px;text-align:right;font-size:16px;font-weight:700;color:var(--pl)}
.stt{text-align:center;font-size:13px;padding:10px;border-radius:10px;margin-top:10px;
  opacity:0;transition:opacity .3s}
.stt.ok{opacity:1;background:#052e16;color:#4ade80}
.stt.ng{opacity:1;background:#450a0a;color:#f87171}
#ps{position:fixed;inset:0;background:#0a0f1e;z-index:999;display:flex;
  flex-direction:column;align-items:center;justify-content:center;padding:40px}
#ps.hidden{display:none}
.pt{font-size:22px;font-weight:700;color:var(--pl);margin-bottom:6px}
.psub{font-size:13px;color:var(--muted);margin-bottom:36px}
.pdots{display:flex;gap:14px;margin-bottom:28px}
.pdot{width:14px;height:14px;border-radius:50%;border:2px solid var(--border);transition:.2s}
.pdot.f{background:var(--primary);border-color:var(--primary)}
.ppad{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;width:240px}
.pk{padding:20px;border-radius:14px;border:1px solid var(--border);background:var(--surface);
  color:var(--text);font-size:22px;font-weight:600;cursor:pointer;text-align:center;
  transition:.15s;user-select:none}
.pk:active{background:var(--border)}.pk.del{font-size:14px;color:var(--muted)}
.perr{color:#f87171;font-size:13px;margin-top:14px;height:18px}
p.note{font-size:12px;color:var(--muted);line-height:1.7;margin-bottom:8px}
</style>
</head>
<body>

<div id="ps">
  <div class="pt">🧠 メンタルトレーニング</div>
  <div class="psub">PINを入力してください</div>
  <div class="pdots">
    <div class="pdot" id="pd0"></div><div class="pdot" id="pd1"></div>
    <div class="pdot" id="pd2"></div><div class="pdot" id="pd3"></div>
  </div>
  <div class="ppad">
    <div class="pk" onclick="pk('1')">1</div><div class="pk" onclick="pk('2')">2</div>
    <div class="pk" onclick="pk('3')">3</div><div class="pk" onclick="pk('4')">4</div>
    <div class="pk" onclick="pk('5')">5</div><div class="pk" onclick="pk('6')">6</div>
    <div class="pk" onclick="pk('7')">7</div><div class="pk" onclick="pk('8')">8</div>
    <div class="pk" onclick="pk('9')">9</div>
    <div class="pk del" onclick="pdel()">←</div>
    <div class="pk" onclick="pk('0')">0</div>
    <div class="pk del" onclick="pclr()">C</div>
  </div>
  <div class="perr" id="perr"></div>
</div>

<div id="app">
  <header class="hdr">
    <div class="hdr-title">🧠 メンタルトレーニング</div>
    <div class="hdr-date" id="dl"></div>
  </header>

  <main id="main">

    <!-- 朝 -->
    <div class="panel active" id="panel-morning">
      <div class="card">
        <div class="ct">💜 ① セルフコンパッション（1分）</div>
        <div class="phrase">
          「今、自分はつらさを感じている。<br>
          これは人間として自然なことだ。<br>
          自分に優しくしていい。」
        </div>
        <div class="cr">
          <div class="cb" id="chk-c" onclick="tog('chk-c')"></div>
          <span>フレーズを唱えた</span>
        </div>
      </div>
      <div class="card">
        <div class="ct">🌬️ ② 横隔膜呼吸（2分）</div>
        <div class="bwrap">
          <div class="bcircle" id="bc-m">
            <div class="bph" id="bm-ph">準備完了</div>
            <div class="bct" id="bm-ct">-</div>
          </div>
          <div class="bdots" id="bm-dots"></div>
          <div class="bsets" id="bm-sets"></div>
        </div>
        <div class="bhint">吸う 4秒 → 止める 2秒 → 吐く 6秒 × 6セット</div>
        <button class="btn bo" id="bm-btn" onclick="startBreath('m',6)">呼吸を開始</button>
        <div class="cr">
          <div class="cb" id="chk-b" onclick="tog('chk-b')"></div>
          <span>呼吸完了（6セット）</span>
        </div>
      </div>
      <button class="btn bp" onclick="saveMorning()">朝のルーティン完了を記録</button>
      <div class="stt" id="st-m"></div>
    </div>

    <!-- 帰宅 -->
    <div class="panel" id="panel-train">
      <div class="card">
        <div class="ct">🔚 ステップ1｜切り替えフレーズ</div>
        <div class="phrase" style="font-size:13px;line-height:2">
          「今日の仕事は終わった。<br>あとは自分の時間だ。<br>今ここにいる自分でいい。」
        </div>
        <div class="cr">
          <div class="cb" id="chk-t1" onclick="tog('chk-t1')"></div>
          <span>フレーズを読んだ</span>
        </div>
      </div>
      <div class="card">
        <div class="ct">🌬️ ステップ2｜呼吸で緊張を流す（約40秒）</div>
        <div class="bwrap">
          <div class="bcircle" id="bc-t">
            <div class="bph" id="bt-ph">準備完了</div>
            <div class="bct" id="bt-ct">-</div>
          </div>
          <div class="bdots" id="bt-dots"></div>
          <div class="bsets" id="bt-sets"></div>
        </div>
        <div class="bhint">吸う 4秒 → 止める 2秒 → 吐く 6秒 × 3セット</div>
        <button class="btn bo" id="bt-btn" onclick="startBreath('t',3)">呼吸を開始</button>
        <div class="cr">
          <div class="cb" id="chk-t2" onclick="tog('chk-t2')"></div>
          <span>呼吸完了</span>
        </div>
      </div>
      <div class="card">
        <div class="ct">🫁 ステップ3｜身体スキャン</div>
        <p class="note">それぞれの部位に意識を向け、息を吐きながら力を抜きます。</p>
        <div class="cr">
          <div class="cb" id="chk-t3a" onclick="tog('chk-t3a')"></div>
          <span>肩 — 息を吐きながら力を落とす</span>
        </div>
        <div class="cr">
          <div class="cb" id="chk-t3b" onclick="tog('chk-t3b')"></div>
          <span>顎 — 口を少し開けて緩める</span>
        </div>
        <div class="cr">
          <div class="cb" id="chk-t3c" onclick="tog('chk-t3c')"></div>
          <span>胸・お腹 — お腹に手を置いて深呼吸</span>
        </div>
      </div>
      <div class="card">
        <div class="ct">👁️ ステップ4｜グラウンディング（今ここに戻る）</div>
        <p class="note">目に見えるものを5つ探して、頭の中から今ここの感覚に切り替えます。</p>
        <div id="glist">
          <div class="gi" id="gr0"><div class="gn">1</div><div class="gt">―</div></div>
          <div class="gi" id="gr1"><div class="gn">2</div><div class="gt">―</div></div>
          <div class="gi" id="gr2"><div class="gn">3</div><div class="gt">―</div></div>
          <div class="gi" id="gr3"><div class="gn">4</div><div class="gt">―</div></div>
          <div class="gi" id="gr4"><div class="gn">5</div><div class="gt">―</div></div>
        </div>
        <button class="btn bo" style="margin-top:12px" onclick="startGround()">カウントを開始</button>
        <div class="cr">
          <div class="cb" id="chk-t4" onclick="tog('chk-t4')"></div>
          <span>5つ確認できた</span>
        </div>
      </div>
    </div>

    <!-- 夜 -->
    <div class="panel" id="panel-evening">
      <div class="card">
        <div class="ct">⚡ ③ 感情トリガーログ（任意）</div>
        <p class="note">怒り・緊張・不安が出た場面があれば記録。なければスキップ可。</p>
        <span class="fl">何があったか（出来事）</span>
        <textarea id="ev" placeholder="例：上司に指摘された、会議で意見が通らなかった" rows="2"></textarea>
        <span class="fl">とっさに思ったこと（解釈パターン）</span>
        <textarea id="th" placeholder="例：また自分だけ責められた、どうせ聞いてもらえない" rows="2"></textarea>
        <span class="fl">身体の反応（肩・胃・顎など）</span>
        <textarea id="bd" placeholder="例：肩が上がった、みぞおちが締まった" rows="2"></textarea>
      </div>
      <div class="card">
        <div class="ct">✨ ④ 今日の良かったこと（自己承認）</div>
        <p class="note">小さいことでOK。結果より「こういう自分でいた」という事実を認める。</p>
        <textarea id="gd" placeholder="例：感情的にならず話を最後まで聞けた" rows="3"></textarea>
      </div>
      <button class="btn bs" onclick="saveEvening()">夜の記録を保存</button>
      <div class="stt" id="st-e"></div>
    </div>

    <!-- 週次 -->
    <div class="panel" id="panel-weekly">
      <div class="card">
        <div class="ct">⚡ 感情パターン振り返り</div>
        <span class="fl">今週、怒り・緊張はどんな場面で出たか？共通するトリガーは？</span>
        <textarea id="w-em" placeholder="例：評価・比較される場面、思い通りにいかない場面" rows="3"></textarea>
      </div>
      <div class="card">
        <div class="ct">🪞 自己評価・他者評価チェック</div>
        <span class="fl">他者の言動に振り回された場面は？そのとき何を信じていたか？</span>
        <textarea id="w-se" placeholder="例：相手の一言で自分の価値が揺らいだ" rows="3"></textarea>
      </div>
      <div class="card">
        <div class="ct">🫁 身体状態（今週 /10）</div>
        <div class="sr">
          <span class="sl">呑気症</span>
          <input type="range" id="w-ae" min="1" max="10" value="5" oninput="usv('w-ae','sv-ae')">
          <span class="sv" id="sv-ae">5</span>
        </div>
        <div class="sr">
          <span class="sl">過緊張</span>
          <input type="range" id="w-te" min="1" max="10" value="5" oninput="usv('w-te','sv-te')">
          <span class="sv" id="sv-te">5</span>
        </div>
        <div class="sr">
          <span class="sl" style="min-width:86px">全体的な緊張感</span>
          <input type="range" id="w-ge" min="1" max="10" value="5" oninput="usv('w-ge','sv-ge')">
          <span class="sv" id="sv-ge">5</span>
        </div>
      </div>
      <div class="card">
        <div class="ct">🌟 今週の良かったこと（自己承認）</div>
        <span class="fl">3つ書いてみましょう（小さいことでOK）</span>
        <textarea id="w-gd" placeholder="1. &#10;2. &#10;3. " rows="5"></textarea>
      </div>
      <div class="card">
        <div class="ct">🧭 自分の軸チェック</div>
        <span class="fl">今週、自分が誇れた行動・判断は？（他者の評価に関係なく、自分として正しいと思えたこと）</span>
        <textarea id="w-pr" placeholder="結果ではなく、自分として正しいと思えた行動・判断を…" rows="3"></textarea>
        <span class="fl">他者の評価に引っ張られた場面を振り返ると、本当は何を大切にしたかった？</span>
        <textarea id="w-rv" placeholder="本当は何を優先したかった？どんな自分でいたかった？" rows="3"></textarea>
      </div>
      <div class="card">
        <div class="ct">🎯 来週の焦点（1つだけ）</div>
        <span class="fl">来週、特に意識したいこと</span>
        <textarea id="w-fo" placeholder="例：怒りを感じたらまず3回深呼吸する" rows="2"></textarea>
      </div>
      <button class="btn bp" onclick="saveWeekly()">週次振り返りを保存</button>
      <div class="stt" id="st-w"></div>
    </div>

  </main>

  <nav class="bnav">
    <button class="ni active" id="nav-morning" onclick="tab('morning')">
      <span class="ico">☀️</span>朝
    </button>
    <button class="ni" id="nav-train" onclick="tab('train')">
      <span class="ico">🚃</span>帰宅
    </button>
    <button class="ni" id="nav-evening" onclick="tab('evening')">
      <span class="ico">🌙</span>夜
    </button>
    <button class="ni" id="nav-weekly" onclick="tab('weekly')">
      <span class="ico">📋</span>週次
    </button>
  </nav>
</div>

<script>
// PIN
let pb='';
function pk(d){if(pb.length>=4)return;pb+=d;udots();if(pb.length===4)subPin()}
function pdel(){pb=pb.slice(0,-1);udots()}
function pclr(){pb='';udots()}
function udots(){for(let i=0;i<4;i++)document.getElementById('pd'+i).classList.toggle('f',i<pb.length)}
async function subPin(){
  try{
    const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pin:pb})});
    const j=await r.json();
    if(j.ok){document.getElementById('ps').classList.add('hidden')}
    else{document.getElementById('perr').textContent='PINが違います';pb='';udots();setTimeout(()=>document.getElementById('perr').textContent='',2000)}
  }catch(e){pb='';udots()}
}
fetch('/api/save-morning',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(3000)})
  .then(r=>{if(r.status!==401)document.getElementById('ps').classList.add('hidden')}).catch(()=>{});

// Date
const _d=new Date();
document.getElementById('dl').textContent=_d.toLocaleDateString('ja-JP',{year:'numeric',month:'long',day:'numeric',weekday:'short'});

// Tabs
const TABS=['morning','train','evening','weekly'];
function tab(name){
  TABS.forEach(n=>{
    document.getElementById('panel-'+n).classList.toggle('active',n===name);
    document.getElementById('nav-'+n).classList.toggle('active',n===name);
  });
  document.getElementById('main').scrollTop=0;
}

// Checkbox
function tog(id){document.getElementById(id).classList.toggle('on')}

// Breathing
const PH=[{n:'吸う',s:4,c:'in'},{n:'止める',s:2,c:'hold'},{n:'吐く',s:6,c:'out'}];
const BS={};
function startBreath(key,total){
  const s=BS[key]||{};
  if(s.timer)clearInterval(s.timer);
  BS[key]={ph:0,sec:0,set:0,total,timer:null};
  const btn=document.getElementById('b'+key+'-btn');
  btn.textContent='実施中…';btn.disabled=true;
  // init dots
  const de=document.getElementById('b'+key+'-dots');
  de.innerHTML='';
  for(let i=0;i<total;i++){const d=document.createElement('div');d.className='bdot';d.id='bd-'+key+'-'+i;de.appendChild(d)}
  btick(key);
  BS[key].timer=setInterval(()=>btick(key),1000);
}
function btick(key){
  const s=BS[key];const ph=PH[s.ph];
  const c=document.getElementById('bc-'+key);
  c.className='bcircle '+ph.c;
  document.getElementById('b'+key+'-ph').textContent=ph.n;
  document.getElementById('b'+key+'-ct').textContent=ph.s-s.sec;
  document.getElementById('b'+key+'-sets').textContent=(s.set+1)+' / '+s.total+' セット';
  // current dot highlight
  const cd=document.getElementById('bd-'+key+'-'+s.set);
  if(cd)cd.className='bdot cur';
  s.sec++;
  if(s.sec>=ph.s){
    s.sec=0;s.ph++;
    if(s.ph>=PH.length){
      s.ph=0;
      if(cd)cd.className='bdot done';
      s.set++;
      if(s.set>=s.total){
        clearInterval(s.timer);s.timer=null;
        c.className='bcircle';
        document.getElementById('b'+key+'-ph').textContent='完了！';
        document.getElementById('b'+key+'-ct').textContent='✓';
        document.getElementById('b'+key+'-sets').textContent=s.total+'セット完了';
        document.getElementById('b'+key+'-btn').textContent='呼吸を開始';
        document.getElementById('b'+key+'-btn').disabled=false;
        const cid=key==='m'?'chk-b':'chk-t2';
        document.getElementById(cid).classList.add('on');
      }
    }
  }
}

// Grounding
const GT=['窓の外に見えるもの','車内で目に入るもの','自分の手元にあるもの','床や座席など触れているもの','遠くに見えるもの'];
let gi=0,gt=null;
function startGround(){
  gi=0;
  for(let i=0;i<5;i++){const el=document.getElementById('gr'+i);el.classList.remove('lit');el.querySelector('.gt').textContent='―'}
  if(gt)clearInterval(gt);
  gt=setInterval(()=>{
    if(gi>=5){clearInterval(gt);document.getElementById('chk-t4').classList.add('on');return}
    const el=document.getElementById('gr'+gi);
    el.querySelector('.gt').textContent=GT[gi];el.classList.add('lit');gi++;
  },1200);
}

function usv(inp,val){document.getElementById(val).textContent=document.getElementById(inp).value}

async function post(url,data){
  const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  return r.json();
}
function showSt(id,msg,ok){
  const el=document.getElementById(id);
  el.textContent=msg;el.className='stt '+(ok?'ok':'ng');
  setTimeout(()=>el.className='stt',4000);
}

async function saveMorning(){
  try{
    const r=await post('/api/save-morning',{
      compassion:document.getElementById('chk-c').classList.contains('on'),
      breath:document.getElementById('chk-b').classList.contains('on')
    });
    showSt('st-m',r.ok?'✓ 朝のルーティンを記録しました':'エラー: '+r.error,r.ok);
  }catch(e){showSt('st-m','サーバーに接続できません',false)}
}
async function saveEvening(){
  try{
    const r=await post('/api/save-evening',{
      trigger_event:document.getElementById('ev').value,
      trigger_thought:document.getElementById('th').value,
      trigger_body:document.getElementById('bd').value,
      good_thing:document.getElementById('gd').value
    });
    showSt('st-e',r.ok?'✓ 夜の記録を保存しました':'エラー: '+r.error,r.ok);
    if(r.ok)['ev','th','bd','gd'].forEach(id=>document.getElementById(id).value='');
  }catch(e){showSt('st-e','サーバーに接続できません',false)}
}
async function saveWeekly(){
  try{
    const r=await post('/api/save-weekly',{
      emotion:document.getElementById('w-em').value,
      self_eval:document.getElementById('w-se').value,
      aerophagia:document.getElementById('w-ae').value,
      tension:document.getElementById('w-te').value,
      general_tension:document.getElementById('w-ge').value,
      good_things:document.getElementById('w-gd').value,
      pride_action:document.getElementById('w-pr').value,
      real_value:document.getElementById('w-rv').value,
      focus:document.getElementById('w-fo').value
    });
    showSt('st-w',r.ok?'✓ 週次振り返りを保存しました':'エラー: '+r.error,r.ok);
  }catch(e){showSt('st-w','サーバーに接続できません',false)}
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
