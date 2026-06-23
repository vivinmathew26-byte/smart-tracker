import http.server
import json
import csv
import io
import os
import urllib.parse
import hashlib
import secrets
from datetime import datetime, date
from collections import defaultdict
import statistics

# ─────────────────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────────────────
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "expenses_data.json")

CATEGORIES = [
    "Food & Dining", "Transportation", "Shopping", "Entertainment",
    "Housing", "Healthcare", "Education", "Travel", "Utilities",
    "Subscriptions", "Personal Care", "Savings", "Other"
]

CAT_ICONS = {
    "Food & Dining": "🍔", "Transportation": "🚗", "Shopping": "🛍️",
    "Entertainment": "🎬", "Housing": "🏠", "Healthcare": "💊",
    "Education": "📚", "Travel": "✈️", "Utilities": "💡",
    "Subscriptions": "📱", "Personal Care": "💆", "Savings": "💰", "Other": "📦"
}

# ─────────────────────────────────────────────────────────
#  DATA LAYER
# ─────────────────────────────────────────────────────────
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                d.setdefault("users", {})
                d.setdefault("sessions", {})
                return d
        except (json.JSONDecodeError, KeyError):
            os.rename(DATA_FILE, DATA_FILE + ".bak")
    return {"users": {}, "sessions": {}}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def get_user_data(data, username):
    if username not in data["users"]:
        data["users"][username] = {
            "password": "",
            "expenses": [],
            "budget": {},
            "next_id": 1
        }
    u = data["users"][username]
    u.setdefault("expenses", [])
    u.setdefault("budget", {})
    u.setdefault("next_id", 1)
    return u


def get_session_user(data, cookie_header):
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith("session="):
            token = part[8:]
            return data.get("sessions", {}).get(token)
    return None


# ─────────────────────────────────────────────────────────
#  ANALYTICS
# ─────────────────────────────────────────────────────────
def compute_analytics(expenses):
    if not expenses:
        return {
            "total": 0, "count": 0, "average": 0, "median": 0,
            "max_expense": 0, "min_expense": 0,
            "by_category": {}, "by_month": {},
            "top_category": "N/A", "top_category_icon": "—",
            "monthly_change": 0, "peak_spending_day": "N/A",
            "today_total": 0, "today_count": 0,
        }

    today_str = date.today().isoformat()
    amounts   = [e["amount"] for e in expenses]
    total     = sum(amounts)
    today_exp = [e for e in expenses if e["date"] == today_str]

    by_category = defaultdict(float)
    by_month    = defaultdict(float)
    dow_totals  = defaultdict(float)

    for e in expenses:
        by_category[e["category"]] += e["amount"]
        by_month[e["date"][:7]]    += e["amount"]
        try:
            dow_totals[datetime.strptime(e["date"], "%Y-%m-%d").strftime("%A")] += e["amount"]
        except ValueError:
            pass

    sorted_months  = sorted(by_month.items())
    monthly_change = 0
    if len(sorted_months) >= 2:
        prev, curr = sorted_months[-2][1], sorted_months[-1][1]
        monthly_change = round(((curr - prev) / prev) * 100, 1) if prev else 0

    top_cat  = max(by_category, key=by_category.get) if by_category else "N/A"
    peak_day = max(dow_totals,  key=dow_totals.get)  if dow_totals  else "N/A"

    return {
        "total":             round(total, 2),
        "count":             len(expenses),
        "average":           round(statistics.mean(amounts), 2),
        "median":            round(statistics.median(amounts), 2),
        "max_expense":       round(max(amounts), 2),
        "min_expense":       round(min(amounts), 2),
        "by_category":       {k: round(v, 2) for k, v in sorted(by_category.items(), key=lambda x: -x[1])},
        "by_month":          {k: round(v, 2) for k, v in sorted_months},
        "top_category":      top_cat,
        "top_category_icon": CAT_ICONS.get(top_cat, "📦"),
        "monthly_change":    monthly_change,
        "peak_spending_day": peak_day,
        "today_total":       round(sum(e["amount"] for e in today_exp), 2),
        "today_count":       len(today_exp),
    }


def generate_insights(expenses, budget):
    insights = []
    if not expenses:
        return insights

    a      = compute_analytics(expenses)
    by_cat = a["by_category"]

    for cat, limit in budget.items():
        spent = by_cat.get(cat, 0)
        if limit <= 0:
            continue
        pct = spent / limit * 100
        if pct >= 100:
            insights.append({"type": "danger",  "icon": "🚨",
                "text": f"Over budget on {cat}! Spent ₹{spent:,.0f} vs ₹{limit:,.0f} limit ({pct:.0f}%)"})
        elif pct >= 80:
            insights.append({"type": "warning", "icon": "⚠️",
                "text": f"Approaching budget for {cat}: ₹{spent:,.0f} of ₹{limit:,.0f} used ({pct:.0f}%)"})

    if by_cat:
        top_name, top_val = list(by_cat.items())[0]
        pct = (top_val / a["total"] * 100) if a["total"] else 0
        insights.append({"type": "info", "icon": "📊",
            "text": f"{top_name} is your biggest spend — {pct:.0f}% of total (₹{top_val:,.0f})"})

    mc = a["monthly_change"]
    if mc > 20:
        insights.append({"type": "warning", "icon": "📈",
            "text": f"Spending jumped {mc}% vs last month. Time to review!"})
    elif mc < -10:
        insights.append({"type": "success", "icon": "📉",
            "text": f"Great work! Spending dropped {abs(mc):.1f}% vs last month."})

    small = [e for e in expenses if e["amount"] < 200]
    if len(small) > 5:
        ts = sum(e["amount"] for e in small)
        insights.append({"type": "info", "icon": "☕",
            "text": f"{len(small)} purchases under ₹200 total ₹{ts:,.0f}. Small habits, big impact!"})

    return insights


# ─────────────────────────────────────────────────────────
#  LOGIN PAGE HTML
# ─────────────────────────────────────────────────────────
LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Login — Smart Expenses Analyzer</title>
<style>
:root{
  --bg:#0d0d14;--surface:#141420;--surface2:#1e1e2e;
  --border:#2c2c44;--accent:#7b68ee;--accent3:#06d6a0;
  --danger:#ef476f;--text:#ebebf5;--muted:#7777aa;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;
  min-height:100vh;display:flex;align-items:center;justify-content:center;}
.box{background:var(--surface);border:1px solid var(--border);border-radius:14px;
  padding:36px 32px;width:100%;max-width:380px;box-shadow:0 20px 60px rgba(0,0,0,.4)}
.brand{text-align:center;margin-bottom:28px}
.brand-icon{font-size:36px}
.brand-name{font-size:20px;font-weight:700;color:var(--accent);margin-top:6px}
.brand-tag{font-size:11px;color:var(--muted);margin-top:2px}
.tabs{display:flex;gap:0;margin-bottom:24px;background:var(--surface2);
  border-radius:8px;padding:3px}
.tab{flex:1;padding:8px;border:none;background:transparent;color:var(--muted);
  cursor:pointer;border-radius:6px;font-size:13px;font-weight:600;transition:all .15s}
.tab.active{background:var(--accent);color:#fff}
.form-group{margin-bottom:14px}
label{display:block;font-size:11px;color:var(--muted);margin-bottom:4px;
  text-transform:uppercase;letter-spacing:.5px}
input{width:100%;background:var(--surface2);border:1px solid var(--border);
  border-radius:7px;color:var(--text);font-size:13px;padding:10px 12px;outline:none;
  transition:border-color .15s}
input:focus{border-color:var(--accent)}
.pass-wrap{position:relative}
.pass-wrap input{padding-right:60px}
.show-btn{position:absolute;right:10px;top:50%;transform:translateY(-50%);
  background:transparent;border:none;color:var(--muted);cursor:pointer;font-size:12px}
.btn{width:100%;padding:11px;border:none;border-radius:8px;font-size:14px;
  font-weight:700;cursor:pointer;margin-top:6px;transition:all .15s}
.btn-login{background:var(--accent);color:#fff}
.btn-login:hover{background:#9585f0}
.msg{text-align:center;font-size:12px;margin-top:12px;padding:8px;border-radius:6px}
.msg.err{background:rgba(239,71,111,.1);color:var(--danger)}
.msg.ok{background:rgba(6,214,160,.1);color:var(--accent3)}
</style>
</head>
<body>
<div class="box">
  <div class="brand">
    <div class="brand-icon">💸</div>
    <div class="brand-name">ExpenseIQ</div>
    <div class="brand-tag">Smart Expenses Analyzer</div>
  </div>

  <div class="tabs">
    <button class="tab active" onclick="switchTab('login')">Login</button>
    <button class="tab" onclick="switchTab('register')">Register</button>
  </div>

  <div id="login-form">
    <div class="form-group">
      <label>Username</label>
      <input type="text" id="l-user" placeholder="Enter username" autocomplete="username">
    </div>
    <div class="form-group">
      <label>Password</label>
      <div class="pass-wrap">
        <input type="password" id="l-pass" placeholder="Enter password"
          autocomplete="current-password" onkeydown="if(event.key==='Enter')doLogin()">
        <button class="show-btn" onclick="togglePass('l-pass')">Show</button>
      </div>
    </div>
    <button class="btn btn-login" onclick="doLogin()">Login →</button>
  </div>

  <div id="register-form" style="display:none">
    <div class="form-group">
      <label>Username</label>
      <input type="text" id="r-user" placeholder="Choose a username">
    </div>
    <div class="form-group">
      <label>Password</label>
      <div class="pass-wrap">
        <input type="password" id="r-pass" placeholder="Choose a password"
          onkeydown="if(event.key==='Enter')doRegister()">
        <button class="show-btn" onclick="togglePass('r-pass')">Show</button>
      </div>
    </div>
    <button class="btn btn-login" onclick="doRegister()">Register →</button>
  </div>

  <div id="msg" class="msg" style="display:none"></div>
</div>

<script>
function switchTab(t){
  document.getElementById('login-form').style.display    = t==='login'    ? '' : 'none';
  document.getElementById('register-form').style.display = t==='register' ? '' : 'none';
  document.querySelectorAll('.tab').forEach(function(b,i){
    b.classList.toggle('active', (i===0&&t==='login')||(i===1&&t==='register'));
  });
  hideMsg();
}

function showMsg(txt, isErr){
  var m = document.getElementById('msg');
  m.textContent = txt;
  m.className = 'msg ' + (isErr ? 'err' : 'ok');
  m.style.display = 'block';
}
function hideMsg(){ document.getElementById('msg').style.display='none'; }

function togglePass(id){
  var el = document.getElementById(id);
  el.type = el.type === 'password' ? 'text' : 'password';
}

async function doLogin(){
  var u = document.getElementById('l-user').value.trim();
  var p = document.getElementById('l-pass').value;
  if(!u||!p){ showMsg('Please fill all fields', true); return; }
  try {
    var res = await fetch('/api/login', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({username:u, password:p})
    });
    var data = await res.json();
    if(data.success){ window.location.href='/'; }
    else { showMsg(data.error || 'Login failed', true); }
  } catch(e){ showMsg('Error: '+e.message, true); }
}

async function doRegister(){
  var u = document.getElementById('r-user').value.trim();
  var p = document.getElementById('r-pass').value;
  if(!u||!p){ showMsg('Please fill all fields', true); return; }
  if(u.length < 3){ showMsg('Username must be at least 3 characters', true); return; }
  if(p.length < 4){ showMsg('Password must be at least 4 characters', true); return; }
  try {
    var res = await fetch('/api/register', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({username:u, password:p})
    });
    var data = await res.json();
    if(data.success){
      showMsg('✅ Registered! Please login now.', false);
      setTimeout(function(){ switchTab('login'); }, 1500);
    } else { showMsg(data.error || 'Registration failed', true); }
  } catch(e){ showMsg('Error: '+e.message, true); }
}
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────
#  MAIN APP HTML
# ─────────────────────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Smart Expenses Analyzer</title>
<style>
:root{
  --bg:#0d0d14;--surface:#141420;--surface2:#1e1e2e;--surface3:#262636;
  --border:#2c2c44;--accent:#7b68ee;--accent2:#ffd166;--accent3:#06d6a0;
  --danger:#ef476f;--success:#06d6a0;--warning:#ffd166;
  --text:#ebebf5;--muted:#7777aa;
  --font:'Segoe UI',system-ui,-apple-system,sans-serif;
  --mono:'Consolas','Courier New',monospace;
  --radius:10px;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--font);min-height:100vh;font-size:14px}
.shell{display:grid;grid-template-columns:220px 1fr;min-height:100vh}
.sidebar{
  background:var(--surface);border-right:1px solid var(--border);
  padding:20px 14px;position:sticky;top:0;height:100vh;
  display:flex;flex-direction:column;gap:4px;overflow-y:auto;
}
.brand{padding:4px 8px 18px;border-bottom:1px solid var(--border);margin-bottom:10px}
.brand-name{font-size:16px;font-weight:700;color:var(--accent)}
.brand-tag{font-size:10px;color:var(--muted);font-family:var(--mono);margin-top:2px}
.brand-user{font-size:11px;color:var(--accent3);margin-top:4px;font-weight:600}
.nav-item{
  display:flex;align-items:center;gap:9px;padding:9px 12px;border-radius:var(--radius);
  border:none;background:transparent;color:var(--muted);cursor:pointer;
  font-family:var(--font);font-size:13px;font-weight:600;transition:all .15s;
  text-align:left;width:100%;
}
.nav-item:hover{background:var(--surface2);color:var(--text)}
.nav-item.active{background:rgba(123,104,238,.2);color:var(--accent)}
.nav-item .ni{font-size:15px;width:20px;text-align:center;flex-shrink:0}
.nav-sep{height:1px;background:var(--border);margin:8px 0}
.nav-section{font-size:9px;color:var(--muted);font-family:var(--mono);
  text-transform:uppercase;letter-spacing:1.2px;padding:4px 12px;margin-top:4px}
.nav-logout{color:var(--danger) !important;}
.nav-logout:hover{background:rgba(239,71,111,.1) !important;}
.main{padding:24px;overflow-y:auto}
.page{display:none;animation:fadeIn .2s ease}
.page.active{display:block}
@keyframes fadeIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
.ph{margin-bottom:22px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px}
.ph-title{font-size:22px;font-weight:700;letter-spacing:-.5px}
.ph-sub{font-size:11px;color:var(--muted);font-family:var(--mono);margin-top:2px}
.sc-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:12px;margin-bottom:20px}
.sc{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  padding:16px;position:relative;overflow:hidden}
.sc::after{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--c,var(--accent))}
.sc-lbl{font-size:10px;color:var(--muted);font-family:var(--mono);text-transform:uppercase;letter-spacing:.8px}
.sc-val{font-size:22px;font-weight:700;margin-top:7px;letter-spacing:-.4px;line-height:1}
.sc-sub{font-size:11px;color:var(--muted);margin-top:5px;font-family:var(--mono)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:18px;margin-bottom:16px}
.card-hdr{font-size:13px;font-weight:700;margin-bottom:14px;display:flex;align-items:center;justify-content:space-between;gap:8px}
.card-hdr-left{display:flex;align-items:center;gap:7px}
.today-grid{display:grid;grid-template-columns:340px 1fr;gap:16px;margin-bottom:16px}
.qf-fields{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px}
.qf-full{grid-column:1/-1}
.form-label{font-size:10px;color:var(--muted);font-family:var(--mono);
  text-transform:uppercase;letter-spacing:.5px;display:block;margin-bottom:4px}
input,select,textarea{
  background:var(--surface2);border:1px solid var(--border);border-radius:7px;
  color:var(--text);font-family:var(--font);font-size:13px;padding:8px 11px;
  transition:border-color .15s;outline:none;width:100%;}
input:focus,select:focus,textarea:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(123,104,238,.15)}
input::placeholder,textarea::placeholder{color:var(--muted)}
select option{background:var(--surface2)}
.btn{padding:8px 16px;border-radius:7px;border:none;cursor:pointer;
  font-family:var(--font);font-size:13px;font-weight:600;transition:all .15s;
  display:inline-flex;align-items:center;gap:6px}
.btn-primary{background:var(--accent);color:#fff}
.btn-primary:hover:not(:disabled){background:#9585f0;transform:translateY(-1px)}
.btn-primary:disabled{opacity:.5;cursor:not-allowed}
.btn-ghost{background:transparent;border:1px solid var(--border);color:var(--muted)}
.btn-ghost:hover{border-color:var(--accent);color:var(--accent)}
.btn-del{background:transparent;border:1px solid transparent;color:var(--muted);padding:4px 8px;font-size:12px;border-radius:6px}
.btn-del:hover{background:rgba(239,71,111,.15);color:var(--danger)}
.btn-sm{padding:5px 11px;font-size:12px}
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
thead th{text-align:left;padding:8px 12px;color:var(--muted);font-family:var(--mono);
  font-size:10px;text-transform:uppercase;letter-spacing:.7px;
  border-bottom:1px solid var(--border);font-weight:500;white-space:nowrap}
tbody td{padding:10px 12px;border-bottom:1px solid rgba(44,44,68,.5);vertical-align:middle}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover td{background:var(--surface2)}
.empty{text-align:center;padding:36px 20px;color:var(--muted);font-family:var(--mono);font-size:12px}
.badge{display:inline-flex;align-items:center;gap:3px;padding:2px 8px;border-radius:20px;
  font-size:11px;font-weight:600;background:rgba(123,104,238,.15);color:var(--accent);white-space:nowrap}
.bars{display:flex;flex-direction:column;gap:8px}
.bar-row{display:flex;align-items:center;gap:9px}
.bar-lbl{font-size:12px;width:130px;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar-track{flex:1;height:7px;background:var(--surface2);border-radius:4px;overflow:hidden}
.bar-fill{height:100%;border-radius:4px;background:var(--accent);transition:width .6s ease}
.bar-amt{font-family:var(--mono);font-size:11px;color:var(--muted);width:80px;text-align:right;flex-shrink:0}
.mchart{display:flex;align-items:flex-end;gap:5px;height:100px}
.mcol{display:flex;flex-direction:column;align-items:center;flex:1;gap:2px;height:100%}
.mcol-wrap{flex:1;display:flex;align-items:flex-end;width:100%}
.mbar{width:100%;border-radius:3px 3px 0 0;background:var(--accent);min-height:3px;transition:height .5s ease}
.mlbl{font-family:var(--mono);font-size:9px;color:var(--muted)}
.mval{font-family:var(--mono);font-size:8px;color:var(--accent2);white-space:nowrap}
.insight{display:flex;align-items:flex-start;gap:10px;padding:11px 13px;
  border-radius:8px;margin-bottom:8px;border-left:3px solid}
.insight.danger{background:rgba(239,71,111,.07);border-color:var(--danger)}
.insight.warning{background:rgba(255,209,102,.07);border-color:var(--warning)}
.insight.success{background:rgba(6,214,160,.07);border-color:var(--success)}
.insight.info{background:rgba(123,104,238,.07);border-color:var(--accent)}
.ins-ico{font-size:15px;flex-shrink:0;margin-top:1px}
.ins-txt{font-size:13px;line-height:1.5}
.bgt-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:11px}
.bgt-card{background:var(--surface2);border:1px solid var(--border);border-radius:9px;padding:13px}
.bgt-name{font-size:12px;font-weight:600;margin-bottom:7px}
.bgt-track{height:5px;background:var(--bg);border-radius:3px;overflow:hidden;margin:5px 0}
.bgt-fill{height:100%;border-radius:3px;transition:width .4s}
.bgt-nums{display:flex;justify-content:space-between;font-family:var(--mono);font-size:10px;color:var(--muted)}
.frow{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.frow input,.frow select{flex:1;min-width:110px}
.today-summary{
  background:linear-gradient(135deg,rgba(123,104,238,.12),rgba(6,214,160,.06));
  border:1px solid rgba(123,104,238,.3);border-radius:var(--radius);padding:18px;
  display:flex;flex-direction:column;gap:6px;justify-content:center;}
.ts-date{font-family:var(--mono);font-size:11px;color:var(--accent);text-transform:uppercase;letter-spacing:.8px}
.ts-total{font-size:32px;font-weight:700;letter-spacing:-1px;margin:4px 0}
.ts-count{font-size:12px;color:var(--muted);font-family:var(--mono)}
.ts-cats{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}
#toast{position:fixed;bottom:18px;right:18px;z-index:9999;background:var(--surface2);
  border:1px solid var(--accent);border-radius:9px;padding:11px 16px;font-size:13px;
  font-weight:600;transform:translateY(60px);opacity:0;transition:all .22s;pointer-events:none}
#toast.show{transform:translateY(0);opacity:1}
#toast.err{border-color:var(--danger)}
.spin{display:inline-block;width:13px;height:13px;border:2px solid rgba(255,255,255,.3);
  border-top-color:#fff;border-radius:50%;animation:sp .6s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}
@media(max-width:720px){
  .shell{grid-template-columns:1fr}
  .sidebar{position:static;height:auto;flex-direction:row;flex-wrap:wrap;
    padding:10px;gap:3px;border-right:none;border-bottom:1px solid var(--border)}
  .brand,.nav-sep,.nav-section{display:none}
  .main{padding:12px}
  .today-grid{grid-template-columns:1fr}
  .qf-fields{grid-template-columns:1fr}
}
</style>
</head>
<body>
<div class="shell">
<aside class="sidebar">
  <div class="brand">
    <div class="brand-name">💸 ExpenseIQ</div>
    <div class="brand-tag">Smart Analyzer v4.0</div>
    <div class="brand-user" id="sidebar-user"></div>
  </div>
  <button class="nav-item active" onclick="nav('dashboard')"><span class="ni">🏠</span>Dashboard</button>
  <div class="nav-sep"></div>
  <div class="nav-section">Manage</div>
  <button class="nav-item" onclick="nav('expenses')"><span class="ni">📋</span>All Expenses</button>
  <button class="nav-item" onclick="nav('analytics')"><span class="ni">📊</span>Analytics</button>
  <div class="nav-sep"></div>
  <div class="nav-section">Plan</div>
  <button class="nav-item" onclick="nav('budget')"><span class="ni">🎯</span>Budget</button>
  <button class="nav-item" onclick="nav('insights')"><span class="ni">💡</span>Insights</button>
  <div class="nav-sep"></div>
  <button class="nav-item nav-logout" onclick="doLogout()"><span class="ni">🚪</span>Logout</button>
</aside>

<main class="main">
  <div id="page-dashboard" class="page active">
    <div class="ph">
      <div class="ph-left">
        <div class="ph-title">Today's Expenses</div>
        <div class="ph-sub" id="today-date-label">// loading...</div>
      </div>
    </div>
    <div class="today-grid">
      <div class="card quick-form" style="margin-bottom:0">
        <div class="card-hdr"><div class="card-hdr-left">➕ Add Expense</div></div>
        <div class="qf-fields">
          <div>
            <label class="form-label">Amount (₹)</label>
            <input type="number" id="f-amount" placeholder="0.00" min="0.01" step="0.01" autofocus>
          </div>
          <div>
            <label class="form-label">Category</label>
            <select id="f-category"></select>
          </div>
          <div class="qf-full">
            <label class="form-label">Description</label>
            <input type="text" id="f-desc" placeholder="What did you spend on?" onkeydown="if(event.key==='Enter')addExpense()">
          </div>
          <div>
            <label class="form-label">Payment</label>
            <select id="f-payment">
              <option>UPI</option><option>Cash</option><option>Credit Card</option>
              <option>Debit Card</option><option>Net Banking</option><option>Other</option>
            </select>
          </div>
          <div>
            <label class="form-label">Notes</label>
            <input type="text" id="f-notes" placeholder="Optional note">
          </div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn btn-primary" id="btn-add" onclick="addExpense()">+ Add</button>
          <button class="btn btn-ghost btn-sm" onclick="clearForm()">Clear</button>
        </div>
      </div>
      <div class="today-summary">
        <div class="ts-date" id="ts-date">TODAY</div>
        <div style="color:var(--muted);font-size:12px;font-family:var(--mono)">Total spent today</div>
        <div class="ts-total" id="ts-total">₹0</div>
        <div class="ts-count" id="ts-count">0 transactions</div>
        <div class="ts-cats" id="ts-cats"></div>
      </div>
    </div>
    <div class="card">
      <div class="card-hdr">
        <div class="card-hdr-left">🧾 Today's Transactions</div>
        <span id="today-badge" style="font-size:11px;color:var(--muted);font-family:var(--mono)"></span>
      </div>
      <div class="table-wrap" id="today-table"></div>
    </div>
    <div class="sc-row" id="dash-stats"></div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
      <div class="card" style="margin-bottom:0">
        <div class="card-hdr"><div class="card-hdr-left">📅 Monthly Trend</div></div>
        <div class="mchart" id="d-mchart"></div>
      </div>
      <div class="card" style="margin-bottom:0">
        <div class="card-hdr"><div class="card-hdr-left">🏷️ Top Categories</div></div>
        <div class="bars" id="d-bars"></div>
      </div>
    </div>
  </div>

  <div id="page-expenses" class="page">
    <div class="ph">
      <div class="ph-left">
        <div class="ph-title">All Expenses</div>
        <div class="ph-sub">// complete transaction history</div>
      </div>
      <button class="btn btn-ghost btn-sm" onclick="exportCSV()">⬇ Export CSV</button>
    </div>
    <div class="frow">
      <input type="text"  id="fl-q"     placeholder="Search..."        oninput="renderAllTable()">
      <select             id="fl-cat"   onchange="renderAllTable()"><option value="">All Categories</option></select>
      <input type="month" id="fl-month" oninput="renderAllTable()">
      <select             id="fl-sort"  onchange="renderAllTable()">
        <option value="date-desc">Newest First</option>
        <option value="date-asc">Oldest First</option>
        <option value="amount-desc">Highest Amount</option>
        <option value="amount-asc">Lowest Amount</option>
      </select>
    </div>
    <div class="card" style="padding:0;overflow:hidden">
      <div class="table-wrap" id="all-table"></div>
    </div>
  </div>

  <div id="page-analytics" class="page">
    <div class="ph">
      <div class="ph-left">
        <div class="ph-title">Analytics</div>
        <div class="ph-sub">// spending patterns & trends</div>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px">
      <div class="card" style="margin-bottom:0">
        <div class="card-hdr"><div class="card-hdr-left">📊 By Category</div></div>
        <div class="bars" id="a-bars"></div>
      </div>
      <div class="card" style="margin-bottom:0">
        <div class="card-hdr"><div class="card-hdr-left">🗓️ Monthly Spending</div></div>
        <div class="mchart" id="a-mchart"></div>
      </div>
    </div>
    <div class="card">
      <div class="card-hdr"><div class="card-hdr-left">📈 Key Statistics</div></div>
      <div id="a-stats" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px"></div>
    </div>
  </div>

  <div id="page-budget" class="page">
    <div class="ph">
      <div class="ph-left">
        <div class="ph-title">Budget Planner</div>
        <div class="ph-sub">// set monthly spending limits</div>
      </div>
    </div>
    <div class="card" style="max-width:420px;margin-bottom:16px">
      <div class="card-hdr"><div class="card-hdr-left">Set Monthly Budget</div></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px">
        <div>
          <label class="form-label">Category</label>
          <select id="b-cat"></select>
        </div>
        <div>
          <label class="form-label">Monthly Limit (₹)</label>
          <input type="number" id="b-amt" placeholder="5000" min="1">
        </div>
      </div>
      <button class="btn btn-primary" onclick="setBudget()">Save Budget</button>
    </div>
    <div class="bgt-grid" id="bgt-grid"></div>
  </div>

  <div id="page-insights" class="page">
    <div class="ph">
      <div class="ph-left">
        <div class="ph-title">Smart Insights</div>
        <div class="ph-sub">// AI-powered spending analysis</div>
      </div>
    </div>
    <div id="ins-wrap"></div>
  </div>
</main>
</div>
<div id="toast"></div>

<script>
var S = {expenses:[], analytics:{}, budget:{}, insights:[], username:''};
var TODAY = new Date().toISOString().split('T')[0];

function nav(page) {
  document.querySelectorAll('.page').forEach(function(p){ p.classList.remove('active'); });
  document.querySelectorAll('.nav-item').forEach(function(b){ b.classList.remove('active'); });
  document.getElementById('page-' + page).classList.add('active');
  document.querySelectorAll('.nav-item').forEach(function(b){
    if (b.textContent.trim().toLowerCase().indexOf(page) !== -1) b.classList.add('active');
  });
  if (page === 'expenses')  renderAllTable();
  if (page === 'analytics') renderAnalytics();
  if (page === 'budget')    renderBudget();
  if (page === 'insights')  renderInsights();
}

async function api(path, opts) {
  opts = opts || {};
  var res = await fetch(path, Object.assign(
    {headers:{'Content-Type':'application/json'}}, opts,
    opts.body ? {body: JSON.stringify(opts.body)} : {}
  ));
  if (res.status === 401) { window.location.href = '/login'; return; }
  if (!res.ok) throw new Error('HTTP ' + res.status);
  return res.json();
}

async function doLogout() {
  await fetch('/api/logout', {method:'POST'});
  window.location.href = '/login';
}

async function init() {
  var d = new Date();
  var opts = {weekday:'long', year:'numeric', month:'long', day:'numeric'};
  set('today-date-label', '// ' + d.toLocaleDateString('en-IN', opts));
  set('ts-date', d.toLocaleDateString('en-IN', {weekday:'long', month:'short', day:'numeric'}).toUpperCase());

  try {
    var cats = await api('/api/categories');
    if (!cats) return;
    ['f-category','fl-cat','b-cat'].forEach(function(id){
      var el = document.getElementById(id);
      if (!el) return;
      if (id === 'fl-cat') el.innerHTML = '<option value="">All Categories</option>';
      else el.innerHTML = '';
      cats.forEach(function(c){
        var o = document.createElement('option');
        o.value = c.name;
        o.textContent = c.icon + ' ' + c.name;
        el.appendChild(o);
      });
    });
  } catch(e) { toast('Failed to load categories', true); }

  await refresh();
}

async function refresh() {
  try {
    var data = await api('/api/data');
    if (!data) return;
    S = data;
    set('sidebar-user', '👤 ' + (S.username || ''));
    renderDashboard();
  } catch(e) { toast('Failed to load data: ' + e.message, true); }
}

function renderDashboard() {
  var a  = S.analytics || {};
  var ex = S.expenses  || [];
  var todayEx = ex.filter(function(e){ return e.date === TODAY; });
  var todayTotal = todayEx.reduce(function(s,e){ return s + e.amount; }, 0);
  set('ts-total', '₹' + fmt(todayTotal));
  set('ts-count', todayEx.length + ' transaction' + (todayEx.length !== 1 ? 's' : ''));
  var todayCats = {};
  todayEx.forEach(function(e){ todayCats[e.category] = (todayCats[e.category]||0) + e.amount; });
  set('ts-cats', Object.entries(todayCats).map(function(r){
    return '<span class="badge">' + escH(r[0]) + ' ₹' + fmt(r[1]) + '</span>';
  }).join(''));
  set('today-badge', todayEx.length + ' entr' + (todayEx.length !== 1 ? 'ies' : 'y') + ' today');
  set('today-table', makeTable(todayEx.slice().sort(function(a,b){ return b.id - a.id; }), true));
  var stats = [
    {l:'All-time Total', v:'₹'+fmt(a.total||0),       c:'--accent',  s:(a.count||0)+' transactions'},
    {l:'This Month',     v:'₹'+fmt(monthlyThis(ex)),   c:'--accent2', s:'vs ₹'+fmt(monthlyLast(ex))+' last month'},
    {l:'Top Category',   v:(a.top_category_icon||'—'), c:'--accent3', s:a.top_category||'—'},
    {l:'Average/Day',    v:'₹'+fmt(avgPerDay(ex)),     c:'--danger',  s:'based on active days'},
  ];
  set('dash-stats', stats.map(function(s){
    return '<div class="sc" style="--c:var('+s.c+')">' +
      '<div class="sc-lbl">'+s.l+'</div>' +
      '<div class="sc-val">'+s.v+'</div>' +
      '<div class="sc-sub">'+s.s+'</div></div>';
  }).join(''));
  renderBarChart('d-bars',   a.by_category || {});
  renderMonthChart('d-mchart', a.by_month  || {});
}

function renderAllTable() {
  var list  = (S.expenses || []).slice();
  var q     = (document.getElementById('fl-q').value     || '').toLowerCase();
  var cat   =  document.getElementById('fl-cat').value   || '';
  var month =  document.getElementById('fl-month').value || '';
  var sort  =  document.getElementById('fl-sort').value  || 'date-desc';
  if (q)     list = list.filter(function(e){ return (e.description+' '+(e.notes||'')).toLowerCase().indexOf(q) !== -1; });
  if (cat)   list = list.filter(function(e){ return e.category === cat; });
  if (month) list = list.filter(function(e){ return e.date.startsWith(month); });
  var p = sort.split('-'), key = p[0], dir = p[1];
  list.sort(function(a,b){
    var av = key==='date' ? a.date : a.amount;
    var bv = key==='date' ? b.date : b.amount;
    return dir==='asc' ? (av>bv?1:-1) : (av<bv?1:-1);
  });
  set('all-table', makeTable(list, true));
}

function renderBarChart(id, data) {
  var el = document.getElementById(id);
  if (!el) return;
  var ent = Object.entries(data);
  if (!ent.length) { el.innerHTML = '<div class="empty">No data yet</div>'; return; }
  var max = Math.max.apply(null, ent.map(function(r){ return r[1]; }));
  el.innerHTML = ent.slice(0,7).map(function(r){
    return '<div class="bar-row">' +
      '<div class="bar-lbl">'+escH(r[0])+'</div>' +
      '<div class="bar-track"><div class="bar-fill" style="width:'+(max?(r[1]/max*100):0)+'%"></div></div>' +
      '<div class="bar-amt">₹'+fmt(r[1])+'</div></div>';
  }).join('');
}

function renderMonthChart(id, data) {
  var el = document.getElementById(id);
  if (!el) return;
  var ent = Object.entries(data).slice(-9);
  if (!ent.length) { el.innerHTML = '<div class="empty" style="align-self:center;width:100%">No data</div>'; return; }
  var max = Math.max.apply(null, ent.map(function(r){ return r[1]; }));
  el.innerHTML = ent.map(function(r){
    var h = max ? Math.max(5, r[1]/max*88) : 5;
    return '<div class="mcol">' +
      '<div class="mval">'+shortFmt(r[1])+'</div>' +
      '<div class="mcol-wrap"><div class="mbar" style="height:'+h+'%"></div></div>' +
      '<div class="mlbl">'+r[0].slice(5)+'</div></div>';
  }).join('');
}

function renderAnalytics() {
  var a = S.analytics || {};
  renderBarChart('a-bars',     a.by_category || {});
  renderMonthChart('a-mchart', a.by_month    || {});
  var items = [
    {l:'Total',     v:'₹'+fmt(a.total||0)},
    {l:'Count',     v:a.count||0},
    {l:'Average',   v:'₹'+fmt(a.average||0)},
    {l:'Median',    v:'₹'+fmt(a.median||0)},
    {l:'Highest',   v:'₹'+fmt(a.max_expense||0)},
    {l:'Lowest',    v:'₹'+fmt(a.min_expense||0)},
    {l:'Monthly Δ', v:(a.monthly_change>=0?'+':'')+(a.monthly_change||0)+'%',
      c:a.monthly_change>0?'var(--danger)':'var(--success)'},
    {l:'Peak Day',  v:a.peak_spending_day||'—'},
    {l:'Today',     v:'₹'+fmt(a.today_total||0), c:'var(--accent2)'},
  ];
  set('a-stats', items.map(function(i){
    return '<div style="background:var(--surface2);padding:12px;border-radius:8px">' +
      '<div style="font-family:var(--mono);font-size:10px;color:var(--muted);text-transform:uppercase">'+i.l+'</div>' +
      '<div style="font-size:18px;font-weight:700;margin-top:5px;color:'+(i.c||'var(--text)')+'">'+i.v+'</div></div>';
  }).join(''));
}

function renderBudget() {
  var budget = S.budget || {};
  var bycat  = (S.analytics || {}).by_category || {};
  var grid   = document.getElementById('bgt-grid');
  var ent    = Object.entries(budget);
  if (!ent.length) {
    grid.innerHTML = '<div style="color:var(--muted);font-family:var(--mono);font-size:12px;grid-column:1/-1">No budgets set yet.</div>';
    return;
  }
  grid.innerHTML = ent.map(function(r){
    var cat = r[0], lim = r[1], spent = bycat[cat]||0;
    var pct = Math.min(spent/lim*100, 100);
    var col = pct>=100?'var(--danger)':pct>=80?'var(--warning)':'var(--success)';
    return '<div class="bgt-card">' +
      '<div class="bgt-name">'+escH(cat)+'</div>' +
      '<div class="bgt-track"><div class="bgt-fill" style="width:'+pct+'%;background:'+col+'"></div></div>' +
      '<div class="bgt-nums"><span>₹'+fmt(spent)+' spent</span><span>'+pct.toFixed(0)+'%</span><span>₹'+fmt(lim)+' limit</span></div>' +
      '<button class="btn btn-del btn-sm" style="margin-top:8px;width:100%" onclick="removeBudget('+JSON.stringify(cat)+')">Remove</button>' +
      '</div>';
  }).join('');
}

function renderInsights() {
  var ins = S.insights || [];
  var el  = document.getElementById('ins-wrap');
  if (!ins.length) {
    el.innerHTML = '<div class="card"><div class="empty">Add more expenses to unlock smart insights!</div></div>';
    return;
  }
  el.innerHTML = '<div class="card"><div class="card-hdr"><div class="card-hdr-left">💡 Recommendations</div></div>' +
    ins.map(function(i){
      return '<div class="insight '+i.type+'"><div class="ins-ico">'+i.icon+'</div>' +
        '<div class="ins-txt">'+escH(i.text)+'</div></div>';
    }).join('') + '</div>';
}

async function addExpense() {
  var amt = parseFloat(document.getElementById('f-amount').value);
  if (!amt || amt <= 0) { toast('Enter a valid amount', true); return; }
  var btn = document.getElementById('btn-add');
  btn.disabled = true; btn.innerHTML = '<span class="spin"></span> Saving...';
  try {
    await api('/api/expenses', {method:'POST', body:{
      amount: amt, date: TODAY,
      category:       document.getElementById('f-category').value,
      description:    document.getElementById('f-desc').value,
      payment_method: document.getElementById('f-payment').value,
      notes:          document.getElementById('f-notes').value,
    }});
    toast('✅ Expense added!');
    clearForm();
    await refresh();
    document.getElementById('f-amount').focus();
  } catch(e) { toast('Error: ' + e.message, true); }
  finally { btn.disabled = false; btn.innerHTML = '+ Add'; }
}

async function deleteExpense(id) {
  if (!confirm('Delete this expense?')) return;
  try {
    await api('/api/expenses/'+id, {method:'DELETE'});
    toast('🗑 Deleted');
    await refresh();
    var ae = document.getElementById('page-expenses');
    if (ae && ae.classList.contains('active')) renderAllTable();
  } catch(e) { toast('Error: '+e.message, true); }
}

async function setBudget() {
  var cat = document.getElementById('b-cat').value;
  var amt = parseFloat(document.getElementById('b-amt').value);
  if (!cat) { toast('Choose a category', true); return; }
  if (!amt || amt <= 0) { toast('Enter a valid limit', true); return; }
  try {
    await api('/api/budget', {method:'POST', body:{category:cat, amount:amt}});
    toast('🎯 Budget saved!');
    document.getElementById('b-amt').value = '';
    await refresh(); renderBudget();
  } catch(e) { toast('Error: '+e.message, true); }
}

async function removeBudget(cat) {
  try {
    await api('/api/budget/'+encodeURIComponent(cat), {method:'DELETE'});
    toast('Budget removed');
    await refresh(); renderBudget();
  } catch(e) { toast('Error: '+e.message, true); }
}

function clearForm() {
  document.getElementById('f-amount').value = '';
  document.getElementById('f-desc').value   = '';
  document.getElementById('f-notes').value  = '';
}

function exportCSV() { window.location.href = '/api/export/csv'; }

function makeTable(list, showDel) {
  if (!list.length) return '<div class="empty">No expenses found</div>';
  var rows = list.map(function(e){
    return '<tr>' +
      '<td style="font-family:var(--mono);font-size:11px;color:var(--muted)">'+escH(e.date)+'</td>' +
      '<td>'+escH(e.description||'—')+'</td>' +
      '<td><span class="badge">'+escH(e.category)+'</span></td>' +
      '<td style="font-family:var(--mono);font-weight:700;color:var(--accent2)">₹'+fmt(e.amount)+'</td>' +
      '<td style="color:var(--muted);font-size:12px">'+escH(e.payment_method||'—')+'</td>' +
      (showDel?'<td><button class="btn btn-del" onclick="deleteExpense('+e.id+')">✕</button></td>':'') +
      '</tr>';
  }).join('');
  return '<table><thead><tr><th>Date</th><th>Description</th><th>Category</th><th>Amount</th><th>Method</th>' +
    (showDel?'<th></th>':'') + '</tr></thead><tbody>'+rows+'</tbody></table>';
}

function fmt(n){ return parseFloat(n).toLocaleString('en-IN',{maximumFractionDigits:0}); }
function shortFmt(n){ return n>=100000?(n/100000).toFixed(1)+'L':n>=1000?(n/1000).toFixed(1)+'k':Math.round(n)+''; }
function set(id, html){ var e=document.getElementById(id); if(e) e.innerHTML=html; }
function escH(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function toast(msg, isErr) {
  var t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'show' + (isErr?' err':'');
  clearTimeout(t._t);
  t._t = setTimeout(function(){ t.className=''; }, 2800);
}
function monthlyThis(expenses) {
  var m = TODAY.slice(0,7);
  return expenses.filter(function(e){ return e.date.startsWith(m); }).reduce(function(s,e){ return s+e.amount; },0);
}
function monthlyLast(expenses) {
  var d = new Date(); d.setMonth(d.getMonth()-1);
  var m = d.toISOString().slice(0,7);
  return expenses.filter(function(e){ return e.date.startsWith(m); }).reduce(function(s,e){ return s+e.amount; },0);
}
function avgPerDay(expenses) {
  if (!expenses.length) return 0;
  var days = new Set(expenses.map(function(e){ return e.date; })).size;
  var total = expenses.reduce(function(s,e){ return s+e.amount; },0);
  return days ? total/days : 0;
}

init();
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────
#  HTTP HANDLER
# ─────────────────────────────────────────────────────────
class Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"  {self.command:7} {self.path}  [{args[1]}]")

    def cors(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204); self.cors(); self.end_headers()

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.cors(); self.end_headers(); self.wfile.write(body)

    def send_html(self, html, extra_headers=None):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type",   "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)

    def redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def read_json(self):
        n = int(self.headers.get("Content-Length", 0))
        if not n: return {}
        try: return json.loads(self.rfile.read(n))
        except json.JSONDecodeError: return {}

    def get_current_user(self):
        d = load_data()
        return get_session_user(d, self.headers.get("Cookie", "")), d

    # ── GET ────────────────────────────────────────
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/login":
            self.send_html(LOGIN_HTML)
            return

        # All other pages require login
        username, d = self.get_current_user()
        if not username:
            self.redirect("/login"); return

        if path in ("/", "/index.html"):
            self.send_html(HTML)

        elif path == "/api/categories":
            self.send_json([{"name": c, "icon": CAT_ICONS.get(c,"📦")} for c in CATEGORIES])

        elif path == "/api/data":
            u = get_user_data(d, username)
            a = compute_analytics(u["expenses"])
            i = generate_insights(u["expenses"], u.get("budget", {}))
            self.send_json({
                "expenses":  u["expenses"],
                "analytics": a,
                "budget":    u.get("budget", {}),
                "insights":  i,
                "username":  username
            })

        elif path == "/api/export/csv":
            u   = get_user_data(d, username)
            buf = io.StringIO()
            w   = csv.DictWriter(buf, fieldnames=["id","date","amount","category",
                                                   "description","payment_method","notes"],
                                 extrasaction="ignore")
            w.writeheader(); w.writerows(u["expenses"])
            b = buf.getvalue().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type",        "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="expenses.csv"')
            self.send_header("Content-Length",      str(len(b)))
            self.cors(); self.end_headers(); self.wfile.write(b)

        else:
            self.send_json({"error": "Not found"}, 404)

    # ── POST ───────────────────────────────────────
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        body = self.read_json()

        # ── REGISTER ──
        if path == "/api/register":
            d        = load_data()
            username = str(body.get("username", "")).strip().lower()
            password = str(body.get("password", ""))
            if not username or not password:
                self.send_json({"error": "Fill all fields"}, 400); return
            if len(username) < 3:
                self.send_json({"error": "Username too short"}, 400); return
            if len(password) < 4:
                self.send_json({"error": "Password too short"}, 400); return
            if username in d["users"]:
                self.send_json({"error": "Username already taken"}); return
            d["users"][username] = {
                "password": hash_password(password),
                "expenses": [], "budget": {}, "next_id": 1
            }
            save_data(d)
            self.send_json({"success": True})
            return

        # ── LOGIN ──
        if path == "/api/login":
            d        = load_data()
            username = str(body.get("username", "")).strip().lower()
            password = str(body.get("password", ""))
            user     = d["users"].get(username)
            if not user or user["password"] != hash_password(password):
                self.send_json({"error": "Invalid username or password"}); return
            token = secrets.token_hex(32)
            d.setdefault("sessions", {})[token] = username
            save_data(d)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie",
                f"session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800")
            body_bytes = json.dumps({"success": True}).encode()
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers(); self.wfile.write(body_bytes)
            return

        # ── LOGOUT ──
        if path == "/api/logout":
            cookie = self.headers.get("Cookie", "")
            d      = load_data()
            for part in cookie.split(";"):
                part = part.strip()
                if part.startswith("session="):
                    token = part[8:]
                    d.get("sessions", {}).pop(token, None)
                    save_data(d)
                    break
            self.send_response(200)
            self.send_header("Set-Cookie", "session=; Path=/; Max-Age=0")
            self.send_header("Content-Length", "2")
            self.send_header("Content-Type", "application/json")
            self.end_headers(); self.wfile.write(b"{}"); return

        # All other POST routes require login
        username, d = self.get_current_user()
        if not username:
            self.send_json({"error": "Unauthorized"}, 401); return

        if path == "/api/expenses":
            try:
                amt = float(body.get("amount", 0)); assert amt > 0
            except (ValueError, AssertionError):
                self.send_json({"error": "Invalid amount"}, 400); return
            u = get_user_data(d, username)
            exp = {
                "id":             u["next_id"],
                "amount":         round(amt, 2),
                "date":           str(body.get("date") or date.today()),
                "category":       str(body.get("category") or "Other"),
                "description":    str(body.get("description", "")).strip(),
                "payment_method": str(body.get("payment_method", "Cash")).strip(),
                "notes":          str(body.get("notes", "")).strip(),
                "created_at":     datetime.now().isoformat(),
            }
            u["expenses"].append(exp)
            u["next_id"] += 1
            save_data(d)
            self.send_json({"success": True, "expense": exp})

        elif path == "/api/budget":
            cat = str(body.get("category", "")).strip()
            try:
                amt = float(body.get("amount", 0)); assert amt > 0 and cat
            except (ValueError, AssertionError):
                self.send_json({"error": "Invalid input"}, 400); return
            u = get_user_data(d, username)
            u.setdefault("budget", {})[cat] = amt
            save_data(d)
            self.send_json({"success": True})

        else:
            self.send_json({"error": "Not found"}, 404)

    # ── DELETE ─────────────────────────────────────
    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path
        username, d = self.get_current_user()
        if not username:
            self.send_json({"error": "Unauthorized"}, 401); return

        u = get_user_data(d, username)

        if path.startswith("/api/expenses/"):
            try: eid = int(path.split("/api/expenses/")[1])
            except ValueError: self.send_json({"error": "Bad id"}, 400); return
            before = len(u["expenses"])
            u["expenses"] = [e for e in u["expenses"] if e["id"] != eid]
            if len(u["expenses"]) < before:
                save_data(d); self.send_json({"success": True})
            else:
                self.send_json({"error": "Not found"}, 404)

        elif path.startswith("/api/budget/"):
            cat = urllib.parse.unquote(path.split("/api/budget/", 1)[1])
            if cat in u.get("budget", {}):
                del u["budget"][cat]; save_data(d)
                self.send_json({"success": True})
            else:
                self.send_json({"error": "Not found"}, 404)
        else:
            self.send_json({"error": "Not found"}, 404)


# ─────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────
def run(port=8000):
    server = http.server.HTTPServer(("0.0.0.0", port), Handler)
    print(f"""
╔══════════════════════════════════════════╗
║  💸  Smart Expenses Analyzer  v4.0       ║
╠══════════════════════════════════════════╣
║  Open  →  http://localhost:{port}           ║
║  Press  Ctrl+C  to stop                  ║
╚══════════════════════════════════════════╝
    """)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n✓ Server stopped.")
        server.server_close()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    run(port)
