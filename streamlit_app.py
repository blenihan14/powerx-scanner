import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, date
import math
from scipy.stats import norm
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import gspread
from google.oauth2.service_account import Credentials

# Page Configuration
st.set_page_config(page_title="PowerX Pro Ultimate Workstation", layout="wide")

st.title("⚡ PowerX Pro Options Workstation & Risk Engine")
st.markdown("Institutional screening, Black-Scholes Greeks, IVR, Macro VIX, Roll Simulator, and Google Sheets journaling.")

# ==========================================
# SIDEBAR: COMPACT CONTROL PANEL & MACRO VIX
# ==========================================
st.sidebar.header("⚙️ Control Panel")

# Live Macro VIX Barometer
try:
    vix_ticker = yf.Ticker("^VIX")
    vix_hist = vix_ticker.history(period="1d")
    current_vix = vix_hist['Close'].iloc[-1] if not vix_hist.empty else 18.0
except:
    current_vix = 18.0

if current_vix < 15:
    vix_status = "🟢 Low Vol (Complacency)"
elif current_vix <= 25:
    vix_status = "🟡 Normal Vol"
else:
    vix_status = "🔴 High Vol (Fear / Spike)"

st.sidebar.markdown(f"**Live VIX:** `{current_vix:.2f}` | **Regime:** {vix_status}")

with st.sidebar.expander("💰 Account & Risk", expanded=True):
    account_size = st.number_input("Account Size ($)", min_value=1000.0, value=50000.0, step=1000.0)
    max_risk_pct = st.slider("Max Capital/Trade (%)", min_value=1.0, max_value=25.0, value=10.0, step=1.0)

with st.sidebar.expander("🎛️ Technical Settings", expanded=False):
    hist_period = st.selectbox("Data Period", ["3mo", "6mo", "1y", "2y"], index=1)
    rsi_window = st.slider("RSI Window", min_value=5, max_value=30, value=14, step=1)
    support_window = st.slider("Support/Resistance (Days)", min_value=10, max_value=100, value=20, step=5)

with st.sidebar.expander("🔍 Scanner Mode & Watchlist", expanded=True):
    scan_mode = st.radio("Mode", ["Single Ticker Deep Dive", "⚡ Batch Screener", "🔄 Roll Simulator", "📊 Beta Delta Tracker"])
    DEFAULT_WATCHLIST = ["VTI", "VOO", "SPY", "QQQ", "MU", "MO", "HD", "AAPL", "NVDA", "TSLA", "AMD"]
    custom_ticker = st.text_input("Add Ticker", "").upper().strip()
    if custom_ticker and custom_ticker not in DEFAULT_WATCHLIST:
        DEFAULT_WATCHLIST.append(custom_ticker)
    selected_ticker = st.selectbox("Target Ticker", DEFAULT_WATCHLIST)

with st.sidebar.expander("🔔 Webhook Alerts", expanded=False):
    notification_type = st.selectbox("Platform", ["None", "Discord Webhook", "Telegram Bot"])
    webhook_url = st.text_input("Endpoint URL", type="password")

def send_webhook_alert(url, message):
    if not url: return False
    try:
        if "discord" in url:
            return requests.post(url, json={"content": message}).status_code == 204
        elif "telegram" in url:
            return requests.get(url).status_code == 200
    except:
        return False

if "scanned" not in st.session_state:
    st.session_state.scanned = False

if st.sidebar.button("Run Scan / Refresh", type="primary"):
    st.session_state.scanned = True

# Helper functions
def calculate_put_greeks(S, K, T_days, iv):
    if T_days <= 0 or iv <= 0 or S <= 0 or K <= 0: return 0.0, 50.0
    T = T_days / 365.0
    r = 0.045
    try:
        d1 = (math.log(S / K) + (r + 0.5 * (iv ** 2)) * T) / (iv * math.sqrt(T))
        delta = norm.cdf(d1) - 1.0
        pop = (1.0 - abs(delta)) * 100.0
        return round(delta, 3), round(pop, 1)
    except:
        return 0.0, 50.0

def log_trade_to_google_sheet(sheet_title, row_data):
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open(sheet_title)
        sheet = spreadsheet.get_worksheet(0)
        sheet.append_row(row_data)
        return True, "Successfully logged trade!"
    except Exception as e:
        return False, str(e)

# ==========================================
# MODE 1: BATCH MARKET SCREENER
# ==========================================
if scan_mode == "⚡ Batch Screener":
    st.subheader("🌐 Automated Watchlist Screener")
    st.markdown(f"Screening watchlist via **{hist_period}** timeframe, **RSI ({rsi_window})**, and **{support_window}D** support.")
    
    if st.button("Run Full Batch Scan", type="primary"):
        results = []
        progress_bar = st.progress(0)
        total = len(DEFAULT_WATCHLIST)
        
        for idx, ticker in enumerate(DEFAULT_WATCHLIST):
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period=hist_period)
                if not hist.empty and len(hist) >= support_window:
                    price = hist['Close'].iloc[-1]
                    delta_p = hist['Close'].diff()
                    gain = (delta_p.where(delta_p > 0, 0)).rolling(window=rsi_window).mean()
                    loss = (-delta_p.where(delta_p < 0, 0)).rolling(window=rsi_window).mean()
                    rsi = 100 - (100 / (1 + (gain / loss))).iloc[-1]
                    support = hist['Low'].rolling(window=support_window).min().iloc[-1]
                    
                    earn_block = False
                    try:
                        cal = stock.calendar
                        if cal and 'Earnings Date' in cal:
                            if 0 <= (pd.to_datetime(cal['Earnings Date'][0]).date() - date.today()).days <= 14:
                                earn_block = True
                    except:
                        pass
                    
                    status = "✅ PASS" if (price <= support * 1.03 and 30 <= rsi <= 55 and not earn_block) else ("⚠️ Earnings" if earn_block else "Watching")
                    results.append({"Ticker": ticker, "Price": round(price, 2), f"RSI": round(rsi, 2), "Support": round(support, 2), "Status": status})
            except:
                pass
            progress_bar.progress((idx + 1) / total)
            
        if results:
            df_res = pd.DataFrame(results)
            st.dataframe(df_res, use_container_width=True)
            st.download_button("📥 Download CSV", data=df_res.to_csv(index=False).encode('utf-8'), file_name="batch_scan.csv", mime="text/csv")

# ==========================================
# MODE 2: ROLL SIMULATOR (MANAGEMENT HELPER)
# ==========================================
elif scan_mode == "🔄 Roll Simulator":
    st.subheader("🔄 Option Roll Simulator")
    st.markdown("Simulate rolling an active short put or covered call out in time to capture net credits and adjust strike basis.")
    
    col_r1, col_r2 = st.columns(2)
    with col_r1:
        roll_strike = st.number_input("Current Strike Price ($)", value=150.0)
        curr_debit = st.number_input("Cost to Buy Back Current Option ($)", value=0.50)
    with col_r2:
        new_strike = st.number_input("New Strike Price ($)", value=145.0)
        new_credit = st.number_input("Credit Received for New Option ($)", value=2.20)
        
    net_credit = new_credit - curr_debit
    st.success(f"**Net Roll Result:** Collect a net credit of **${net_credit:.2f} per share** (${net_credit * 100:,.2f} total per contract) while shifting strike to${new_strike}.")

# ==========================================
# MODE 3: PORTFOLIO BETA-WEIGHTED DELTA TRACKER
# ==========================================
elif scan_mode == "📊 Beta Delta Tracker":
    st.subheader("📊 Portfolio Beta-Weighted Delta Tracker")
    st.markdown("Estimate net market directional exposure relative to SPY.")
    
    col_b1, col_b2, col_b3 = st.columns(3)
    with col_b1:
        p_ticker = st.text_input("Position Ticker", value="AAPL")
        p_delta = st.number_input("Option Delta", value=-0.25)
    with col_b2:
        p_contracts = st.number_input("Contracts", value=2, min_value=1)
        p_beta = st.number_input("Beta vs SPY", value=1.2)
    with col_b3:
        spy_price = st.number_input("Current SPY Price ($)", value=580.0)
        
    beta_weighted_delta = p_delta * p_contracts * 100 * p_beta
    spy_equiv_shares = beta_weighted_delta / (spy_price / 100) # approximation context
    
    st.info(f"**Net Beta-Weighted Delta:** `{beta_weighted_delta:.1f}` | Equivalent to holding approx. `{int(beta_weighted_delta)}` shares of SPY.")

# ==========================================
# MODE 4: SINGLE TICKER DEEP DIVE
# ==========================================
elif scan_mode == "Single Ticker Deep Dive":
    if st.session_state.scanned:
        with st.spinner(f"Analyzing {selected_ticker}..."):
            stock = yf.Ticker(selected_ticker)
            hist = stock.history(period=hist_period)
            
            if hist.empty or len(hist) < support_window:
                st.error(f"Insufficient historical data for {selected_ticker}.")
            else:
                price = hist['Close'].iloc[-1]
                delta_p = hist['Close'].diff()
                gain = (delta_p.where(delta_p > 0, 0)).rolling(window=rsi_window).mean()
                loss = (-delta_p.where(delta_p < 0, 0)).rolling(window=rsi_window).mean()
                hist['RSI'] = 100 - (100 / (1 + (gain / loss)))
                hist['Support'] = hist['Low'].rolling(window=support_window).min()
                hist['Resistance'] = hist['High'].rolling(window=support_window).max()
                
                rsi = hist['RSI'].iloc[-1]
                support = hist['Support'].iloc[-1]
                resistance = hist['Resistance'].iloc[-1]
                
                # Approximate IVR/IV Percentile using rolling volatility
                hist['Returns'] = hist['Close'].pct_change()
                hist['HistVol'] = hist['Returns'].rolling(20).std() * math.sqrt(252)
                current_iv_approx = hist['HistVol'].iloc[-1] * 1.25 # proxy
                hv_min, hv_max = hist['HistVol'].min(), hist['HistVol'].max()
                ivr = max(0.0, min(100.0, ((current_iv_approx - hv_min) / (hv_max - hv_min + 1e-6)) * 100))

                earn_warn = False
                try:
                    cal = stock.calendar
                    if cal and 'Earnings Date' in cal:
                        if 0 <= (pd.to_datetime(cal['Earnings Date'][0]).date() - date.today()).days <= 14:
                            earn_warn = True
                except:
                    pass

                ex_div_str = "None"
                ex_div_warn = False
                try:
                    ts = stock.info.get('exDividendDate')
                    if ts:
                        ex_d = pd.to_datetime(ts, unit='s').date()
                        ex_div_str = ex_d.strftime('%Y-%m-%d')
                        if 0 <= (ex_d - date.today()).days <= 30:
                            ex_div_warn = True
                except:
                    pass

                with st.expander(f"📈 Metrics & Signals: {selected_ticker}", expanded=True):
                    c1, c2, c3, c4, c5 = st.columns(5)
                    c1.metric("Price", f"${price:.2f}")
                    c2.metric(f"RSI ({rsi_window})", f"{rsi:.1f}")
                    c3.metric("Support", f"${support:.2f}")
                    c4.metric("Resistance", f"${resistance:.2f}")
                    c5.metric("IVR (Approx)", f"{ivr:.0f}%")
                    
                    if earn_warn: st.error("🚨 Earnings within 14 days!")
                    if ex_div_warn: st.warning(f"⚠️ Ex-Dividend date approaching ({ex_div_str})!")

                with st.expander(f"📉 Price & RSI Chart", expanded=True):
                    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
                    fig.add_trace(go.Scatter(x=hist.index, y=hist['Close'], name='Close', line=dict(color='blue')), row=1, col=1)
                    fig.add_trace(go.Scatter(x=hist.index, y=hist['Support'], name='Support', line=dict(color='green', dash='dash')), row=1, col=1)
                    fig.add_trace(go.Scatter(x=hist.index, y=hist['Resistance'], name='Resistance', line=dict(color='red', dash='dash')), row=1, col=1)
                    fig.add_trace(go.Scatter(x=hist.index, y=hist['RSI'], name='RSI', line=dict(color='purple')), row=2, col=1)
                    fig.update_layout(height=400, margin=dict(l=5, r=5, t=5, b=5), template="plotly_white", legend=dict(orientation="h", y=1.02, x=1))
                    st.plotly_chart(fig, use_container_width=True)

                with st.expander("📊 Options Chain & Position Sizing", expanded=True):
                    try:
                        exp_dates = stock.options
                        if exp_dates:
                            target_date = st.selectbox("Expiry", exp_dates)
                            puts = stock.option_chain(target_date).puts
                            if not puts.empty:
                                dte = max(1, (datetime.strptime(target_date, "%Y-%m-%d").date() - date.today()).days)
                                otm = puts[puts['strike'] < support].copy()
                                if otm.empty: otm = puts[puts['strike'] < price * 0.95].copy()
                                if otm.empty: otm = puts.copy()
                                
                                otm['Delta'], otm['PoP_%'] = zip(*[calculate_put_greeks(price, r['strike'], dte, r.get('impliedVolatility', 0.3)) for _, r in otm.iterrows()])
                                otm['Yield_%'] = (otm['bid'] / otm['strike']) * 100
                                max_cap = account_size * (max_risk_pct / 100.0)
                                otm['Max_Contracts'] = (max_cap / (otm['strike'] * 100)).astype(int)
                                otm['Collateral'] = otm['strike'] * otm['Max_Contracts'] * 100
                                
                                cols = ['strike', 'bid', 'ask', 'impliedVolatility', 'Delta', 'PoP_%', 'Yield_%', 'Max_Contracts', 'Collateral']
                                st.dataframe(otm[cols].sort_values(by='bid', ascending=False), use_container_width=True)
                                st.download_button("📥 Download Chain CSV", data=otm[cols].to_csv(index=False).encode('utf-8'), file_name=f"{selected_ticker}_chain.csv", mime="text/csv")
                    except Exception as e:
                        st.warning(f"Options chain error: {e}")

                with st.expander("📝 Log Trade to Google Sheets", expanded=False):
                    with st.form("j_form"):
                        sh_title = st.text_input("Sheet Title", value="options_trading_tracker-v5")
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            t_id = st.text_input("Trade ID", value="T-015")
                            strat = st.selectbox("Strategy", ["Cash-Secured Put", "Covered Call"])
                        with c2:
                            strike = st.number_input("Strike", value=round(support, 2))
                            contracts = st.number_input("Contracts", value=1, min_value=1)
                        with c3:
                            prem = st.number_input("Premium/Share", value=1.50)
                            notes = st.text_input("Notes", value="Logged via Streamlit")
                        
                        if st.form_submit_button("🚀 Push to Sheet"):
                            row = [t_id, str(date.today()), selected_ticker, strat, "Put", f"${strike:.2f}", str(date.today()), "30", str(contracts), f"${prem:.2f}", f"${prem*contracts*100:.2f}", f"${strike*contracts*100:,.2f}", "$0.01", f"${price:.2f}", "0.30", f"{rsi:.1f}%", f"RSI support", "", "Open", "", "", "", "", "", "", notes]
                            success, msg = log_trade_to_google_sheet(sh_title, row)
                            if success: st.success(msg)
                            else: st.error(msg)
    else:
        st.info("👈 Select your ticker in the sidebar and click **Run Scan / Refresh**.")
