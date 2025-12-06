import streamlit as st
import pandas as pd
import subprocess
import sys
import os
import signal
import time
import csv
import json
import hmac
import hashlib
from pathlib import Path
try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv(*args, **kwargs):
        return False
import sqlite3
try:
    import razorpay
except ImportError:
    razorpay = None

# --- Configuration ---
st.set_page_config(
    page_title="Scraper Pro",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

BASE_DIR = Path(__file__).resolve().parent
SCRAPER_SCRIPT = str(BASE_DIR / "asin.py")
CHECKPOINT_FILE = str(BASE_DIR / "fetched_asins.txt")
CSV_FILE = str(BASE_DIR / "products_export.csv")
PID_FILE = str(BASE_DIR / "scraper.pid")
DEDUCTED_FILE = str(BASE_DIR / "deducted_count.txt")
DEFAULT_EXCEL = ""
DB_FILE = str(BASE_DIR / "users.db")
PENDING_SUFFIX = ".pending.json"

# --- SQLite setup and credit helpers ---
def _db_conn():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
                    email TEXT PRIMARY KEY,
                    credits INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS credit_transactions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          email TEXT NOT NULL,
          delta INTEGER NOT NULL,
          reason TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    return conn

DB = _db_conn()

# Ensure schema has password_hash column even if DB existed before
try:
    cols = DB.execute("PRAGMA table_info(users)").fetchall()
    names = {c[1] for c in cols}
    if "password_hash" not in names:
        DB.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        DB.commit()
    if "settings" not in names:
        DB.execute("ALTER TABLE users ADD COLUMN settings TEXT")
        DB.commit()
except Exception:
    pass

def ensure_user(email: str):
    if not email:
        return
    DB.execute("INSERT OR IGNORE INTO users(email, credits) VALUES(?, 0)", (email,))
    DB.commit()

def _safe_email(email: str) -> str:
    return email.replace("@", "_at_").replace(".", "_")

def _pending_path(email: str) -> str:
    safe = _safe_email(email)
    return str(BASE_DIR / (safe + PENDING_SUFFIX))

def save_pending_order(email: str, order: dict):
    try:
        with open(_pending_path(email), "w") as f:
            json.dump(order, f)
    except Exception as e:
        st.error(f"Failed to save pending order: {e}")

def load_pending_order(email: str) -> dict | None:
    try:
        path = _pending_path(email)
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return None

def clear_pending_order(email: str):
    try:
        path = _pending_path(email)
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

PLANS = {
    "200k": {"price": 100.00, "credits": 200_000},
    "1M": {"price": 180.00, "credits": 1_000_000},
}

def _secret_or_env(key: str, default: str = "") -> str:
    try:
        # Prefer Streamlit Cloud secrets when available
        return st.secrets.get(key, default)  # type: ignore[attr-defined]
    except Exception:
        return os.getenv(key, default)

RAZORPAY_KEY_ID = _secret_or_env("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = _secret_or_env("RAZORPAY_KEY_SECRET", "")
RAZORPAY_CURRENCY = _secret_or_env("RAZORPAY_CURRENCY", "USD")

def load_credits(email: str) -> int:
    if not email:
        return 0
    ensure_user(email)
    cur = DB.execute("SELECT credits FROM users WHERE email=?", (email,))
    row = cur.fetchone()
    return int(row[0]) if row else 0

def set_password(email: str, password: str):
    ensure_user(email)
    ph = hashlib.sha256((password or "").encode()).hexdigest()
    DB.execute("UPDATE users SET password_hash=? WHERE email=?", (ph, email))
    DB.commit()

def verify_password(email: str, password: str) -> bool:
    cur = DB.execute("SELECT password_hash FROM users WHERE email=?", (email,))
    row = cur.fetchone()
    ph = row[0] if row else None
    if ph is None:
        return False
    return ph == hashlib.sha256((password or "").encode()).hexdigest()

def add_credits(email: str, delta: int, reason: str | None = None):
    if not email or delta == 0:
        return
    ensure_user(email)
    current = load_credits(email)
    new_val = max(0, current + int(delta))
    DB.execute("UPDATE users SET credits=? WHERE email=?", (new_val, email))
    DB.execute(
        "INSERT INTO credit_transactions(email, delta, reason) VALUES(?, ?, ?)",
        (email, int(delta), reason or "add")
    )
    DB.commit()

def deduct_credits(email: str, delta: int, reason: str | None = None) -> bool:
    if not email or delta <= 0:
        return False
    current = load_credits(email)
    if current < delta:
        return False
    new_val = current - delta
    DB.execute("UPDATE users SET credits=? WHERE email=?", (new_val, email))
    DB.execute(
        "INSERT INTO credit_transactions(email, delta, reason) VALUES(?, ?, ?)",
        (email, -int(delta), reason or "deduct")
    )
    DB.commit()
    return True

def get_user_settings(email: str) -> dict:
    if not email:
        return {}
    try:
        cur = DB.execute("SELECT settings FROM users WHERE email=?", (email,))
        row = cur.fetchone()
        if row and row[0]:
            return json.loads(row[0])
    except:
        pass
    return {}

def update_user_settings(email: str, settings: dict):
    if not email:
        return
    try:
        s_json = json.dumps(settings)
        DB.execute("UPDATE users SET settings=? WHERE email=?", (s_json, email))
        DB.commit()
    except:
        pass

if "credits" not in st.session_state:
    st.session_state["credits"] = 0
if "user_email" not in st.session_state:
    st.session_state["user_email"] = ""
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "pending_order" not in st.session_state:
    st.session_state["pending_order"] = None
if "selected_plan" not in st.session_state:
    st.session_state["selected_plan"] = None
if "deducted_fetched" not in st.session_state:
    st.session_state["deducted_fetched"] = 0

load_dotenv()  # Load .env from project root

# --- Custom CSS ---
st.markdown("""
<style>
    :root {
        --bg-gradient-start:#0d1117;
        --bg-gradient-end:#121e30;
        --panel-bg:#141b27;
        --panel-border:#263245;
        --panel-border-strong:#345274;
        --accent:#3b82f6;
        --accent-glow:#60a5fa;
        --accent-rgb:59,130,246;
        --danger:#ef4444;
        --warning:#f59e0b;
        --success:#10b981;
        --text-primary:#f0f6ff;
        --text-secondary:#9fb1c5;
        --text-faint:#6b7a89;
        --radius-sm:6px;
        --radius-md:10px;
        --radius-lg:16px;
        --transition:0.18s ease;
        --shadow-md:0 4px 12px rgba(0,0,0,0.35);
        --shadow-lg:0 10px 32px rgba(0,0,0,0.55);
    }
    .stApp {
        background: radial-gradient(circle at 20% 20%, var(--bg-gradient-start) 0%, var(--bg-gradient-end) 60%);
        color: var(--text-primary);
        font-family: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen;
    }
    section[data-testid="stSidebar"] {background:linear-gradient(180deg,#101722 0%,#0d141d 100%);border-right:1px solid var(--panel-border);}
    /* Scrollbar */
    ::-webkit-scrollbar { width: 10px; }
    ::-webkit-scrollbar-track { background: #0d141d; }
    ::-webkit-scrollbar-thumb { background: #1f2b38; border-radius: var(--radius-sm); }
    ::-webkit-scrollbar-thumb:hover { background: #2c3d52; }
    /* Headings */
    h1,h2,h3 { font-weight:600; letter-spacing:.5px; }
    /* Metric cards */
    div[data-testid="stMetric"] {
        background: var(--panel-bg);
        border:1px solid var(--panel-border);
        border-radius: var(--radius-md);
        padding:14px 16px;
        box-shadow: var(--shadow-md);
        position:relative;
    }
    div[data-testid="stMetric"]:hover {border-color: var(--panel-border-strong); box-shadow:0 6px 18px rgba(0,0,0,0.5);}
    div[data-testid="stMetricLabel"] { color: var(--text-secondary)!important; font-size:.75rem; text-transform:uppercase; letter-spacing:.08em; }
    div[data-testid="stMetricValue"] { color: var(--accent-glow)!important; font-weight:600; text-shadow:0 0 8px rgba(var(--accent-rgb),0.35); }
    /* Terminal */
    .terminal-box {
        background:#0a0f14;
        border:1px solid #1e2b38;
        border-radius: var(--radius-md);
        padding:16px;
        font-family: 'JetBrains Mono','Courier New',monospace;
        font-size:12px;
        color:#7efb7e;
        box-shadow: inset 0 0 12px rgba(0,0,0,0.6), var(--shadow-md);
    }
    /* Buttons */
    button[kind="primary"], .pay-btn {background:var(--accent)!important; color:#081422!important; font-weight:600; box-shadow:0 4px 14px rgba(var(--accent-rgb),0.35);}
    button[kind="primary"]:hover, .pay-btn:hover {background:var(--accent-glow)!important; box-shadow:0 6px 20px rgba(var(--accent-rgb),0.55);}
    button[kind="secondary"] {background:#223041!important; color:var(--text-secondary)!important;}
    button[kind="secondary"]:hover {background:#2a3d52!important;}
    /* Inputs */
    .stTextInput input, .stNumberInput input, .stTextArea textarea {background:#182433; border:1px solid #263245; color:var(--text-primary);}
    .stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus {border-color:var(--accent); box-shadow:0 0 0 1px var(--accent);}
    /* Plan cards */
    .plans .plan {position:relative; overflow:hidden;}
    .plans .plan:before {content:""; position:absolute; inset:0; background:linear-gradient(135deg,rgba(var(--accent-rgb),0.15),transparent 60%); opacity:0; transition:var(--transition);}
    .plans .plan:hover:before {opacity:1;}
    .plans .plan {border:1px solid var(--panel-border); background:#141e29;}
    .plans .plan:hover {border-color: var(--panel-border-strong); box-shadow: var(--shadow-lg); transform:translateY(-2px);}
    .plans .price {font-size:1.25rem; text-shadow:0 0 12px rgba(var(--accent-rgb),0.4);}
    /* Navbar */
    .top-navbar {backdrop-filter: blur(6px); background:rgba(13,19,27,0.85)!important;}
    /* Info boxes */
    .stAlert {background:#15202b!important; border:1px solid #253446!important;}
    /* Dataframe tweaks */
    .stDataFrame {background:#101722; border:1px solid #1f2b30; border-radius: var(--radius-md);}
    /* Footer spacing removal */
    footer {visibility:hidden; height:0;}
</style>
""", unsafe_allow_html=True)

# Hide Streamlit default toolbar/decorations
st.markdown("""
    <style>
        .reportview-container { margin-top: -2em; }
        #stDecoration { display: none; }
        .stDeployButton { display: none; }
        [data-testid="stToolbar"] { visibility: hidden; height: 0%; position: fixed; }
        [data-testid="stDecoration"] { visibility: hidden; height: 0%; }
        [data-testid="stStatusWidget"] { visibility: hidden; }
    </style>
""", unsafe_allow_html=True)

# --- Helper Functions ---

def get_total_asins(file_path):
    try:
        df = pd.read_excel(file_path)
        # Filter empty
        clean_asins = [str(a).strip() for a in df.values.flatten() if pd.notna(a) and str(a).strip() != ""]
        return len(sorted(list(set(clean_asins))))
    except:
        return 0

def get_stats():
    fetched = 0
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r") as f:
            fetched = sum(1 for line in f if line.strip())
            
    successful = 0
    if os.path.exists(CSV_FILE):
        try:
            # Count unique handles in CSV
            df_csv = pd.read_csv(CSV_FILE)
            if "Handle" in df_csv.columns:
                successful = df_csv["Handle"].nunique()
        except:
            pass
            
    skipped = fetched - successful
    return fetched, successful, skipped

def get_deducted_count():
    if os.path.exists(DEDUCTED_FILE):
        try:
            with open(DEDUCTED_FILE, "r") as f:
                return int(f.read().strip())
        except:
            return 0
    return 0

def update_deducted_count(count):
    try:
        with open(DEDUCTED_FILE, "w") as f:
            f.write(str(count))
    except:
        pass

def is_running():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, 0) # Check if process exists
            return True
        except (OSError, ValueError):
            os.remove(PID_FILE)
    return False

def start_scraper(input_file, category, p_type, formula):
    if is_running():
        st.toast("⚠️ Scraper is already running!")
        return
    if st.session_state["credits"] < 1:
        st.error("Not enough credits to start. Purchase a plan.")
        return
    if not input_file or not os.path.exists(input_file):
        st.error("Please upload a valid .xlsx file before starting.")
        return
    # Reset progressive deduction baseline
    update_deducted_count(get_stats()[0])
    
    update_deducted_count(get_stats()[0])
    
    with open(str(BASE_DIR / "scraper.log"), "a") as log_file:
        log_file.write(f"\n\n{'='*40}\nStarting Scraper: {time.strftime('%Y-%m-%d %H:%M:%S')}\n{'='*40}\n")
        process = subprocess.Popen(
            [sys.executable, "-u", SCRAPER_SCRIPT, input_file, category, p_type, formula],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=str(BASE_DIR)
        )
    
    with open(PID_FILE, "w") as f:
        f.write(str(process.pid))
    st.toast("🚀 Scraper started successfully!")
    time.sleep(1)
    st.rerun()

def stop_scraper():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
            st.toast("🛑 Scraper stopped.")
        except Exception as e:
            st.error(f"Error stopping: {e}")
        finally:
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
            time.sleep(1)
            st.rerun()
    else:
        st.info("Scraper is not running.")

def reset_stats():
    if is_running():
        st.error("Please stop the scraper first!")
    else:
        if os.path.exists(CHECKPOINT_FILE): os.remove(CHECKPOINT_FILE)
        if os.path.exists(CSV_FILE): os.remove(CSV_FILE)
        log_path = str(BASE_DIR / "scraper.log")
        if os.path.exists(log_path): os.remove(log_path)
        if os.path.exists(DEDUCTED_FILE): os.remove(DEDUCTED_FILE)
        # Do not reset credits here
        st.toast("♻️ Stats and files reset!")
        time.sleep(1)
        st.rerun()

def create_razorpay_order(plan_key: str):
    if razorpay is None:
        st.error("Razorpay SDK not installed.")
        return None
    if not (RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET):
        st.error("Razorpay keys not configured.")
        return None
    client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    plan = PLANS[plan_key]
    # Razorpay expects amount in smallest currency unit (cents for USD)
    amount_minor = int(plan["price"] * 100)
    receipt = f"plan_{plan_key}_{int(time.time())}"
    try:
        order = client.order.create({
            "amount": amount_minor,
            "currency": RAZORPAY_CURRENCY,
            "receipt": receipt,
            "notes": {"credits": plan["credits"], "plan": plan_key},
        })
    except Exception as e:
        st.error(f"Failed to create order: {e}")
        return None
    st.session_state["pending_order"] = {"order_id": order["id"], "plan": plan_key, "credits": plan["credits"]}
    return order

def verify_payment(order_id: str, payment_id: str, signature: str):
    body = f"{order_id}|{payment_id}".encode()
    expected = hmac.new(RAZORPAY_KEY_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

# --- Sidebar ---
def render_navbar():
    # Custom CSS for the sticky header
    st.markdown("""
        <style>
        .block-container {
            padding-top: 1rem;
            padding-bottom: 1rem;
        }
        .header-container {
            position: sticky;
            top: 0;
            z-index: 999;
            background: #161b22;
            padding: 10px 20px;
            border-bottom: 1px solid #30363d;
            margin-bottom: 20px;
            margin-top: -1rem; /* Counteract remaining padding if needed */
        }
        .header-title {
            font-size: 1.2rem;
            font-weight: 700;
            color: #fff;
            display: flex;
            align-items: center;
            height: 100%;
        }
        .user-info {
            color: #a0a0a0;
            font-size: 0.9rem;
            display: flex;
            align-items: center;
            justify-content: flex-end;
            height: 100%;
            gap: 15px;
        }
        .credits-val {
            color: #0fd;
            font-weight: 600;
        }
        /* Adjust button styling in header */
        .header-btn button {
            padding: 0.25rem 0.75rem;
            min-height: auto;
        }
        </style>
    """, unsafe_allow_html=True)

    with st.container():
        st.markdown('<div class="header-container">', unsafe_allow_html=True)
        
        c1, c2, c3, c4 = st.columns([2, 3, 1, 1])
        
        with c1:
            st.markdown('<div class="header-title">🚀 Scraper Pro</div>', unsafe_allow_html=True)
            
        with c2:
            u_email = st.session_state.get("user_email", "-")
            u_credits = st.session_state.get("credits", 0)
            st.markdown(
                f"""
                <div class="user-info">
                    <span>{u_email}</span>
                    <span>Credits: <span class="credits-val">{u_credits}</span></span>
                </div>
                """, 
                unsafe_allow_html=True
            )
            
        with c3:
            st.markdown('<div class="header-btn">', unsafe_allow_html=True)
            if st.button("Add Credits", type="primary", use_container_width=True, key="hdr_add_credits"):
                # Logic to scroll to plans or just show toast
                st.toast("Scroll down to purchase plans!")
            st.markdown('</div>', unsafe_allow_html=True)
            
        with c4:
            st.markdown('<div class="header-btn">', unsafe_allow_html=True)
            if st.button("Logout", use_container_width=True, key="hdr_logout"):
                st.session_state["logged_in"] = False
                st.session_state["user_email"] = ""
                st.session_state["credits"] = 0
                st.session_state["pending_order"] = None
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)

def render_login():
    st.title("🔐 Login to Scraper Pro")
    email = st.text_input("Email", value=st.session_state.get("user_email", ""), placeholder="user@example.com")
    password = st.text_input("Password", type="password", placeholder="••••••••")
    col_l, col_r = st.columns(2)
    with col_l:
        if st.button("Login", type="primary", use_container_width=True):
            ensure_user(email)
            if verify_password(email, password):
                st.session_state["user_email"] = email
                st.session_state["credits"] = load_credits(email)
                st.session_state["logged_in"] = True
                st.success("Logged in successfully.")
                st.rerun()
            else:
                st.error("Invalid email or password.")
    with col_r:
        if st.button("Create Account", use_container_width=True):
            if not email or not password:
                st.error("Enter email and password to register.")
            else:
                set_password(email, password)
                st.session_state["user_email"] = email
                st.session_state["credits"] = load_credits(email)
                st.session_state["logged_in"] = True
                st.success("Account created and logged in.")
                st.rerun()

if not st.session_state.get("logged_in"):
    render_login()
    st.stop()

render_navbar()

# Sidebar configuration (after login): keep only data and settings; move plans/payment to main
with st.sidebar:
    st.title("⚙️ Configuration")
    
    st.markdown("### 1. Data Source")
    uploaded_file = st.file_uploader("Upload ASIN List (.xlsx)", type=["xlsx"])
    
    target_file = DEFAULT_EXCEL
    if uploaded_file:
        target_path = BASE_DIR / "uploaded_asins.xlsx"
        with open(target_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        target_file = str(target_path)
        st.success(f"Loaded: {uploaded_file.name}")
    
    total_asins = get_total_asins(target_file)
    st.metric("Total Target ASINs", total_asins)
    
    st.markdown("### 3. Pricing Rules")
    
    # Load settings
    user_settings = get_user_settings(st.session_state.get("user_email"))
    
    # Defaults
    def_formula = user_settings.get("price_formula", "x")
    def_category = user_settings.get("product_category", "Health & Supplements")
    def_type = user_settings.get("product_type", "Dietary Supplement")

    price_formula = st.text_input("Price Formula (use 'x' as price)", value=def_formula, help="Example: 'x * 1.5' to increase by 50%, or 'x + 10' to add $10")

    st.markdown("### 4. CSV Settings")
    product_category = st.text_input("Product Category", value=def_category)
    product_type = st.text_input("Product Type", value=def_type)
    
    # Save settings if changed
    new_settings = {
        "price_formula": price_formula,
        "product_category": product_category,
        "product_type": product_type
    }
    if new_settings != user_settings and st.session_state.get("user_email"):
        update_user_settings(st.session_state["user_email"], new_settings)

    # Capture payment verification from query params
    qp = st.experimental_get_query_params()
    if {"payment_id", "order_id", "signature"}.issubset(qp.keys()) and st.session_state.get("pending_order"):
        pay_id = qp["payment_id"][0]
        ord_id = qp["order_id"][0]
        sig = qp["signature"][0]
        po = st.session_state["pending_order"]
        if ord_id == po["order_id"] and verify_payment(ord_id, pay_id, sig):
            add_credits(st.session_state["user_email"], po["credits"], reason=f"purchase {po['plan']}")
            st.session_state["credits"] = load_credits(st.session_state["user_email"])
            st.session_state["pending_order"] = None
            clear_pending_order(st.session_state["user_email"])
            st.experimental_set_query_params()  # Clear params to avoid double credit
            st.success(f"Payment verified. Added {po['credits']} credits.")
        else:
            st.error("Payment verification failed. Check order/payment IDs and signature.")

    st.markdown("### 6. System Status")
    if is_running():
        st.success("🟢 System Online: Scraper Running")
    else:
        st.warning("🔴 System Offline: Scraper Stopped")

# --- Main Dashboard ---
st.title("Product Scraper")

# --- Plans & Payment (Main area) ---
st.markdown("### 💠 Plans & Credits")
st.markdown(
    """
    <style>
    .plans { display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap:16px; }
    .plan { background:#12161f; border:1px solid #253046; border-radius:12px; padding:16px; }
    .plan h4 { margin:0 0 6px 0; color:#eaf2ff; }
    .plan p { margin:0 0 12px 0; color:#a7b1c2; }
    .plan .price { font-weight:700; color:#5dd8ff; }
    .plan button { width:100%; padding:10px 14px; border:none; border-radius:8px; background:#00a2ff; color:#00111a; font-weight:700; cursor:pointer; }
    </style>
    """,
    unsafe_allow_html=True,
)
colA, colB = st.columns(2)
with colA:
    st.markdown("""
    <div class='plans'>
      <div class='plan'>
        <h4>Starter</h4>
        <p>200,000 credits</p>
        <div class='price'>$100</div>
      </div>
    </div>
    """, unsafe_allow_html=True)
with colB:
    st.markdown("""
    <div class='plans'>
      <div class='plan'>
        <h4>Pro</h4>
        <p>1,000,000 credits</p>
        <div class='price'>$180</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

colBtns = st.columns(2)
with colBtns[0]:
    starter_buy = st.button("Buy Starter (200k / $100)", use_container_width=True)
with colBtns[1]:
    pro_buy = st.button("Buy Pro (1M / $180)", use_container_width=True)

plan_choice = None
if starter_buy:
    plan_choice = "200k"
elif pro_buy:
    plan_choice = "1M"

if plan_choice:
    if not st.session_state["user_email"]:
        st.error("Please login first.")
    else:
        ensure_user(st.session_state["user_email"])
        order = create_razorpay_order(plan_choice)
        if order:
            save_pending_order(st.session_state["user_email"], {"order_id": order["id"], "plan": plan_choice, "credits": PLANS[plan_choice]["credits"]})
            st.session_state["pending_order"] = load_pending_order(st.session_state["user_email"]) or st.session_state["pending_order"]
            st.success("Order created. Scroll down to checkout.")

st.markdown("### 📊 Live Performance Metrics")

fetched_count, success_count, skipped_count = get_stats()

# --- Checkout Section (main area) ---
if st.session_state.get("pending_order"):
        po = st.session_state["pending_order"]
        st.info(f"Pending Order: {po['order_id']} | Plan {po['plan']} -> {po['credits']} credits")
        if RAZORPAY_KEY_ID:
                checkout_html = f"""
                <style>
                    .checkout-container {{
                        display:flex; align-items:center; justify-content:center;
                        min-height: 60vh; padding: 24px;
                        background: #0e1117; color: #fff;
                    }}
                    .pay-card {{
                        max-width: 520px; width: 100%;
                        background:#161b22; border:1px solid #30363d; border-radius:12px;
                        padding:24px; text-align:center; box-shadow: 0 10px 20px rgba(0,0,0,0.35);
                    }}
                    .pay-title {{ font-size:20px; font-weight:600; margin-bottom:8px; }}
                    .pay-desc {{ font-size:14px; color:#a0a0a0; margin-bottom:16px; }}
                    .pay-btn {{
                        width:100%; padding:12px 16px; border-radius:8px; border:none;
                        background:#00a2ff; color:#00111a; font-weight:700; cursor:pointer;
                    }}
                </style>
                <div class="checkout-container">
                    <div class="pay-card">
                        <div class="pay-title">Checkout</div>
                        <div class="pay-desc">Plan {po['plan']} · Amount {(PLANS[po['plan']]['price']):.2f} {RAZORPAY_CURRENCY}</div>
                        <button id='rzp-button' class='pay-btn'>Pay Now</button>
                    </div>
                </div>
                <script src='https://checkout.razorpay.com/v1/checkout.js'></script>
                <script>
                    var options = {{
                        key: '{RAZORPAY_KEY_ID}',
                        amount: {int(PLANS[po['plan']]['price']*100)},
                        currency: '{RAZORPAY_CURRENCY}',
                        name: 'Scraper Credits',
                        description: 'Plan {po['plan']}',
                        order_id: '{po['order_id']}',
                        handler: function (response) {{
                            var params = new URLSearchParams({{
                                payment_id: response.razorpay_payment_id,
                                order_id: response.razorpay_order_id,
                                signature: response.razorpay_signature
                            }}).toString();
                            window.location.href = window.location.pathname + '?' + params;
                        }},
                        theme: {{ color: '#3399cc' }}
                    }};
                    function openCheckout(e) {{
                        var rzp1 = new Razorpay(options); rzp1.open(); if(e) e.preventDefault();
                    }}
                    document.getElementById('rzp-button').addEventListener('click', openCheckout);
                </script>
                """
                st.components.v1.html(checkout_html, height=600, scrolling=False)

# Progress Bar
if total_asins > 0:
    progress = min(fetched_count / total_asins, 1.0)
    st.progress(progress, text=f"Overall Progress: {int(progress*100)}%")
else:
    st.progress(0, text="Waiting for data...")

# Metric Cards
m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric("Fetched Products", fetched_count, delta=None)
with m2:
    st.metric("Successful Exports", success_count, delta=f"{success_count/fetched_count*100:.1f}% Rate" if fetched_count else "0%")
with m3:
    st.metric("Skipped (No Price)", skipped_count, delta_color="inverse")
with m4:
    remaining = total_asins - fetched_count
    st.metric("Remaining", max(0, remaining))

st.markdown("---")

# --- Control Center ---
st.markdown("### 🎮 Control Center")
c1, c2 = st.columns([1, 1])

with c1:
    st.markdown("#### Operations")
    col_op1, col_op2 = st.columns(2)
    with col_op1:
        if st.button("▶️ Start Scraping", type="primary", use_container_width=True, disabled=is_running()):
            start_scraper(target_file, product_category, product_type, price_formula)
    with col_op2:
        if st.button("⏹️ Stop Scraping", type="secondary", use_container_width=True, disabled=not is_running()):
            stop_scraper()

with c2:
    st.markdown("#### Data Management")
    col_data1, col_data2, col_data3 = st.columns(3)
    
    with col_data1:
        if os.path.exists(CSV_FILE):
            with open(CSV_FILE, "rb") as f:
                st.download_button("📥 CSV", f, "products_export.csv", "text/csv", use_container_width=True)
        else:
            st.button("📥 CSV", disabled=True, use_container_width=True)
            
    with col_data2:
        if os.path.exists(CHECKPOINT_FILE):
            # Generate stats file content
            stats_header = (
                f"Total Fetched: {fetched_count}\n"
                f"Successful Scrapes: {success_count}\n"
                f"Skipped (No Price): {skipped_count}\n"
                f"{'-'*30}\n"
            )
            with open(CHECKPOINT_FILE, "r") as f:
                full_content = stats_header + f.read()
            st.download_button("📋 Log", full_content, "fetched_asins_with_stats.txt", "text/plain", use_container_width=True)
        else:
            st.button("📋 Log", disabled=True, use_container_width=True)

    with col_data3:
        if st.button("🗑️ Reset", type="primary", use_container_width=True, help="Clear all data"):
            reset_stats()

# --- Terminal View ---
st.markdown("### 📟 Live Terminal")
log_placeholder = st.empty()

def render_terminal():
    log_path = BASE_DIR / "scraper.log"
    if os.path.exists(log_path):
        with open(log_path, "r") as f:
            lines = f.readlines()
            # Show last 20 lines like before
            log_content = "".join(lines[-20:])
            log_placeholder.code(log_content)
    else:
        log_placeholder.info("No logs yet.")

if is_running():
    # Progressive credit deduction per fetched product
    current_fetched = get_stats()[0]
    prev_deducted = get_deducted_count()
    delta = current_fetched - prev_deducted
    if delta > 0:
        if st.session_state["credits"] >= delta:
            if deduct_credits(st.session_state["user_email"], delta, reason="scrape"):
                st.session_state["credits"] = load_credits(st.session_state["user_email"])
                update_deducted_count(current_fetched)
                # st.toast(f"Deducted {delta} credits. Remaining: {st.session_state['credits']}")
            else:
                st.error("Out of credits. Stopping scraper.")
                stop_scraper()
    for _ in range(10):  # Refresh loop
        render_terminal()
        time.sleep(0.5)
    st.rerun()
else:
    render_terminal()


