import streamlit as st

# Page config
st.set_page_config(page_title="Pricing", page_icon="💳", layout="wide")

# Reuse the same theme styles as main app
st.markdown(
    """
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
    --text-primary:#f0f6ff;
    --text-secondary:#9fb1c5;
    --radius-md:10px;
    --shadow-md:0 4px 12px rgba(0,0,0,0.35);
    --shadow-lg:0 10px 32px rgba(0,0,0,0.55);
  }
  .stApp { background: radial-gradient(circle at 20% 20%, var(--bg-gradient-start) 0%, var(--bg-gradient-end) 60%); color: var(--text-primary); }
  .plans { display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 18px; margin-top: 8px; }
  .plan { border:1px solid var(--panel-border); background:#141e29; border-radius: var(--radius-md); padding:18px; box-shadow: var(--shadow-md); transition: .18s ease; }
  .plan:hover { border-color: var(--panel-border-strong); box-shadow: var(--shadow-lg); transform: translateY(-2px); }
  .plan .title { font-weight:600; font-size:1.1rem; color:var(--text-primary); }
  .plan .subtitle { color:var(--text-secondary); font-size:.9rem; margin-top:2px; }
  .plan .price { font-size:1.6rem; font-weight:700; color:var(--accent-glow); margin:10px 0 2px; text-shadow:0 0 12px rgba(var(--accent-rgb),0.4); }
  .plan .unit { color:var(--text-secondary); font-size:.85rem; }
  .features { margin-top:10px; color:var(--text-secondary); font-size:.95rem; }
  .features li { margin: 6px 0; }
  .cta { margin-top:14px; display:flex; gap:10px; }
  .btn { padding:8px 12px; border-radius:8px; font-weight:600; text-decoration:none; display:inline-block; }
  .btn-primary { background:var(--accent); color:#081422; }
  .btn-outline { border:1px solid var(--panel-border); color:var(--text-secondary); }
  .btn:hover { filter:brightness(1.08); }
</style>
""",
    unsafe_allow_html=True,
)

# Hide Streamlit default toolbar/decorations
st.markdown(
  """
  <style>
    .reportview-container { margin-top: -2em; }
    #stDecoration { display: none; }
    .stDeployButton { display: none; }
    [data-testid=\"stToolbar\"] { visibility: hidden; height: 0%; position: fixed; }
    [data-testid=\"stDecoration\"] { visibility: hidden; height: 0%; }
    [data-testid=\"stStatusWidget\"] { visibility: hidden; }
    footer { visibility: hidden; height: 0; }
    .viewerBadge_container__rK4r { display: none !important; }
    .stAppDeployButton { display: none !important; }
  </style>
  """,
  unsafe_allow_html=True,
)

st.title("Pricing")
st.caption("Choose the plan that fits your scale. Upgrade anytime.")

col_intro, col_link = st.columns([0.7, 0.3])
with col_intro:
    st.markdown(
        "Upgrade credits for your scraping workflow. Prices are one-time purchases; credits never expire."
    )
with col_link:
    # Link back to main app checkout
    try:
        st.page_link("app.py", label="Go to Checkout →")
    except Exception:
        st.write("Go to the main app to purchase: http://localhost:8501")

st.markdown("---")

st.markdown(
    """
<div class="plans">
  <div class="plan">
    <div class="title">Starter</div>
    <div class="subtitle">For testing and small jobs</div>
    <div class="price">$100 <span class="unit">one-time</span></div>
    <div class="subtitle">200,000 credits</div>
    <ul class="features">
      <li>Progressive per-product credit usage</li>
      <li>No expiration on credits</li>
    </ul>
    <div class="cta">
      <a class="btn btn-primary title" href="#" onclick="window.location.href='/'">Buy on Checkout</a>
    </div>
  </div>
  <div class="plan">
    <div class="title">Pro</div>
    <div class="subtitle">Large, consistent scraping</div>
    <div class="price">$180 <span class="unit">one-time</span></div>
    <div class="subtitle">1,000,000 credits</div>
    <ul class="features">
      <li> Progressive per-product credit usage</li>
      <li>No expiration on credits</li>
    </ul>
    <div class="cta">
      <a class="btn btn-primary title" href="#" onclick="window.location.href='/'">Buy on Checkout</a>
    </div>
  </div>
  
""",
    unsafe_allow_html=True,
)

st.markdown("""
#### What are credits?
Credits represent the unit of scraping work. Your balance decreases progressively as products are scraped. Unused credits never expire.
""")

st.markdown("""
#### How to purchase
Use the Checkout on the main page to complete a secure Razorpay payment. Your account is credited automatically after verification.
""")
