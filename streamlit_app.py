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

# Page Configuration (Compact Layout)
st.set_page_config(page_title="PowerX Pro Ultimate Workstation", layout="wide", initial_sidebar_state="expanded")

st.markdown("### ⚡ PowerX Pro Institutional Options Workstation")
st.markdown("Portfolio Greeks, Earnings Expected Move, P&L Payoffs, Backtester, IVR, VIX, Roll Simulator, & Journaling.")

# ==========================================
# SIDEBAR: COMPACT CONTROL PANEL & MACRO VIX
# ==========================================
st.sidebar.header("⚙️ Control Panel")

try:
    vix_close = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
except:
    vix_close = 18.0

vix_badge = "🟢 Low" if vix_close < 15 else ("🟡 Normal" if vix_close <= 25 else "🔴 High")
st.sidebar.caption(f"**VIX:** `{vix_close:.2f}` ({vix_badge})")

with st.sidebar.expander("💰 Account & Risk", expanded=True):
    account_size = st.number_input("Account ($)", min_value=1000.0, value=50000.0, step=1000.0, format="%.0f")
    max_risk_pct = st.slider("Max Risk/Trade (%)", min_value=1.0, max_value=25.0, value=10.0, step=1.0)

with st.sidebar.expander("🎛️ Technical Settings", expanded=False):
    hist_period = st.selectbox("Period", ["3mo", "6mo", "1y", "2y"], index=1)
    rsi_window = st.slider("RSI Window", 5, 30, 14, 1)
    support_window = st.slider("Support Window (Days)", 10, 100, 20, 5)

with st.sidebar.expander("🔍 Navigation", expanded=True):
    scan_mode = st.radio("Mode", ["Single Ticker Deep Dive", "⚡ Batch Screener", "🔄 Roll Simulator", "📊 Portfolio Greeks & Journal", "🧪 Backtester & Earnings"])
    DEFAULT_WATCHLIST = ["VTI", "VOO", "SPY", "QQQ", "MU", "MO", "HD", "AAPL", "NVDA", "TSLA", "AMD"]
    custom_t = st.sidebar.text_input("Add Ticker", "").upper().strip()
    if custom_t and custom_t not in DEFAULT_WATCHLIST: DEFAULT_WATCHLIST.append(custom_t)
    selected_ticker = st.sidebar.selectbox("Target Ticker", DEFAULT_WATCHLIST)

with st.sidebar.expander("🔔 Webhooks", expanded=False):
    webhook_url = st.sidebar.text_input("Webhook URL", type="password")

def send_alert(url, msg):
    if not url: return False
    try:
        if "discord" in url: return requests.post(url, json={"content": msg}).status_code == 204
        elif "telegram" in url: return requests.get(url).status_code == 200
    except: return False

if "scanned" not in st.session_state: st.session_state.scanned = False
if st.sidebar.button("Run Scan / Refresh", type="primary"): st.session_state.scanned = True

# Helper functions for Greeks & Sheets
def calculate_greeks(S, K, T_days, iv, opt_type="Put"):
    if T_days <= 0 or iv <= 0 or S <= 0 or K <= 0: return 0.0, 0.0, 0.0, 50.0
    T = T_days / 365.0
    r = 0.045
    try:
        d1 = (math.log(S / K) + (r + 0.5 * (iv ** 2)) * T) / (iv * math.sqrt(T))
        d2 = d1 - iv * math.sqrt(T)
        nd1 = norm.pdf(d1)
        if opt_type == "Put":
            delta = norm.cdf(d1) - 1.0
            theta = (- (S * nd1 * iv) / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * norm.cdf(-d2)) / 365.0
        else:
            delta = norm.cdf(d1)
            theta = (- (S * nd1 * iv) / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * norm.cdf(d2)) / 365.0
        vega = (S * math.sqrt(T) * nd1) / 100.0
        pop = (1.0 - abs(delta)) * 100.0
        return round(delta, 3), round(theta, 2), round(vega, 2), round(pop, 1)
    except:
        return 0.0, 0.0, 0.0, 50.0

def get_google_sheet_records(sheet_title):
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        client = gspread.authorize(creds)
        return client.open(sheet_title).get_worksheet(0).get_all_records()
    except:
        return []

def log_trade(sheet_title, row_data):
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        client = gspread.authorize(creds)
        client.open(sheet_title).get_worksheet(0).append_row(row_data)
        return True, "Successfully logged!"
    except Exception as e:
        return False, str(e)

# ==========================================
# MODE 1: BATCH SCREENER
# ==========================================
if scan_mode == "⚡ Batch Screener":
    st.subheader("⚡ Automated Watchlist Screener")
    if st.button("Run Batch Scan", type="primary"):
        res = []
        bar = st.progress(0)
        tot = len(DEFAULT_WATCHLIST)
        for idx, t in enumerate(DEFAULT_WATCHLIST):
            try:
                stk = yf.Ticker(t)
                h = stk.history(period=hist_period)
                if not h.empty and len(h) >= support_window:
                    p = h['Close'].iloc[-1]
                    dp = h['Close'].diff()
                    rsi = 100 - (100 / (1 + (dp.where(dp>0,0).rolling(rsi_window).mean() / -dp.where(dp<0,0).rolling(rsi_window).mean()))).iloc[-1]
                    sup = h['Low'].rolling(support_window).min().iloc[-1]
                    earn = False
                    try:
                        cal = stk.calendar
                        if cal and 'Earnings Date' in cal:
                            if 0 <= (pd.to_datetime(cal['Earnings Date'][0]).date() - date.today()).days <= 14: earn = True
                    except: pass
                    stat = "✅ PASS" if (p <= sup * 1.03 and 30 <= rsi <= 55 and not earn) else ("⚠️ Earnings" if earn else "Watching")
                    res.append({"Ticker": t, "Price": round(p,2), "RSI": round(rsi,1), "Support": round(sup,2), "Status": stat})
            except: pass
            bar.progress((idx + 1) / tot)
        if res:
            df = pd.DataFrame(res)
            st.dataframe(df, use_container_width=True)
            st.download_button("📥 Download CSV", df.to_csv(index=False).encode('utf-8'), "batch_scan.csv", "text/csv")

# ==========================================
# MODE 2: ROLL SIMULATOR
# ==========================================
elif scan_mode == "🔄 Roll Simulator":
    st.subheader("🔄 Option Roll Simulator")
    c1, c2 = st.columns(2)
    with c1:
        r_strike = st.number_input("Current Strike ($)", value=150.0)
        c_debit = st.number_input("Cost to Close ($)", value=0.50)
    with c2:
        n_strike = st.number_input("New Strike ($)", value=145.0)
        n_credit = st.number_input("New Credit ($)", value=2.20)
    net_c = n_credit - c_debit
    st.success(f"**Net Roll:** Collect **${net_c:.2f}/share** (${net_c*100:,.2f} total) while moving strike to${n_strike}.")

# ==========================================
# MODE 3: PORTFOLIO GREEKS & JOURNAL
# ==========================================
elif scan_mode == "📊 Portfolio Greeks & Journal":
    st.subheader("📊 Aggregate Portfolio Greeks & Open Trades")
    sheet_name = st.text_input("Google Sheet Title", value="options_trading_tracker-v5")
    records = get_google_sheet_records(sheet_name)
    
    if records:
        df_rec = pd.DataFrame(records)
        open_trades = df_rec[df_rec['Status'].astype(str).str.lower() == 'open'] if 'Status' in df_rec.columns else pd.DataFrame()
        
        if not open_trades.empty:
            tot_delta, tot_theta, tot_vega = 0.0, 0.0, 0.0
            for _, row in open_trades.iterrows():
                try:
                    s_ticker = str(row.get('Ticker', 'AAPL'))
                    strike = float(str(row.get('Strike Price', '0')).replace('$', '').replace(',', ''))
                    contracts = int(float(str(row.get('Contracts', '1'))))
                    o_type = str(row.get('Option Type', 'Put'))
                    exp_str = str(row.get('Expiration Date', str(date.today())))
                    dte = max(1, (datetime.strptime(exp_str[:10], "%Y-%m-%d").date() - date.today()).days)
                    
                    stk_info = yf.Ticker(s_ticker).history(period="1d")
                    cur_p = stk_info['Close'].iloc[-1] if not stk_info.empty else strike
                    iv = 0.30
                    
                    d, th, vg, _ = calculate_greeks(cur_p, strike, dte, iv, o_type)
                    multiplier = 100 * contracts * (-1 if o_type=="Put" else 1) # short put delta is negative exposure adjustment
                    tot_delta += d * contracts * 100
                    tot_theta += th * contracts * 100
                    tot_vega += vg * contracts * 100
                except:
                    pass
            
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("Aggregate Delta", f"{tot_delta:.1f}")
            mc2.metric("Aggregate Theta ($/day)", f"${tot_theta:,.2f}")
            mc3.metric("Aggregate Vega", f"{tot_vega:.1f}")
            
            st.markdown("##### Open Journal Positions")
            st.dataframe(open_trades, use_container_width=True)
        else:
            st.info("No open positions found in the Google Sheet.")
    else:
        st.warning("Could not connect or fetch records from the specified Google Sheet.")

# ==========================================
# MODE 4: BACKTESTER & EARNINGS
# ==========================================
elif scan_mode == "🧪 Backtester & Earnings":
    st.subheader("🧪 Strategy Backtester & Earnings Expected Move")
    c_bt1, c_bt2 = st.columns(2)
    with c_bt1:
        bt_ticker = st.text_input("Backtest Ticker", value="AAPL")
    with c_bt2:
        bt_years = st.selectbox("Historical Span", ["1y", "2y", "5y"], index=1)
        
    if st.button("Run Historical Backtest"):
        with st.spinner(f"Running simulation for {bt_ticker}..."):
            bt_hist = yf.Ticker(bt_ticker).history(period=bt_years)
            if not bt_hist.empty:
                bt_hist['Delta'] = bt_hist['Close'].diff()
                bt_hist['RSI'] = 100 - (100 / (1 + (bt_hist['Delta'].where(bt_hist['Delta']>0,0).rolling(14).mean() / -bt_hist['Delta'].where(bt_hist['Delta']<0,0).rolling(14).mean())))
                bt_hist['Support'] = bt_hist['Low'].rolling(20).min()
                
                signals = bt_hist[(bt_hist['Close'] <= bt_hist['Support'] * 1.03) & (bt_hist['RSI'].between(30, 55))]
                wins = 0
                total_trades = len(signals)
                
                for idx, row in signals.iterrows():
                    loc_idx = bt_hist.index.get_loc(idx)
                    if loc_idx + 20 < len(bt_hist):
                        exit_p = bt_hist['Close'].iloc[loc_idx + 20]
                        if exit_p >= row['Close'] * 0.98: # won or survived pullback
                            wins += 1
                
                win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
                st.success(f"**Backtest Results for {bt_ticker}:** Tested {total_trades} historical pullback signals over {bt_years}. **Win Rate (20D survival):** `{win_rate:.1f}%`")
            else:
                st.error("Insufficient historical data for backtest.")

    st.markdown("---")
    st.markdown("##### 📅 Earnings Expected Move Calculator")
    e_ticker = st.text_input("Ticker for Earnings Check", value="NVDA")
    try:
        e_stock = yf.Ticker(e_ticker)
        e_price = e_stock.history(period="1d")['Close'].iloc[-1]
        exps = e_stock.options
        if exps:
            chain = e_stock.option_chain(exps[0])
            atm_put = chain.puts.iloc[(chain.puts['strike'] - e_price).abs().argsort()[:1]]
            atm_call = chain.calls.iloc[(chain.calls['strike'] - e_price).abs().argsort()[:1]]
            straddle_price = float(atm_put['lastPrice'].values[0]) + float(atm_call['lastPrice'].values[0])
            em_pct = (straddle_price / e_price) * 100
            st.info(f"**{e_ticker} Nearest Expiry Straddle Cost:** `${straddle_price:.2f}` | **Market Priced Expected Move:** `±{em_pct:.1f}%`")
    except:
        st.info("Unable to calculate earnings expected move right now.")

# ==========================================
# MODE 5: SINGLE TICKER DEEP DIVE
# ==========================================
elif scan_mode == "Single Ticker Deep Dive":
    if st.session_state.scanned:
        with st.spinner(f"Analyzing {selected_ticker}..."):
            stk = yf.Ticker(selected_ticker)
            hist = stk.history(period=hist_period)
            
            if hist.empty or len(hist) < support_window:
                st.error(f"Insufficient data for {selected_ticker}.")
            else:
                price = hist['Close'].iloc[-1]
                dp = hist['Close'].diff()
                rsi = 100 - (100 / (1 + (dp.where(dp>0,0).rolling(rsi_window).mean() / -dp.where(dp<0,0).rolling(rsi_window).mean()))).iloc[-1]
                sup = hist['Low'].rolling(support_window).min().iloc[-1]
                res = hist['High'].rolling(support_window).max().iloc[-1]
                
                # Approx IVR
                hv = hist['Close'].pct_change().rolling(20).std() * math.sqrt(252)
                iv_approx = hv.iloc[-1] * 1.25
                ivr = max(0.0, min(100.0, ((iv_approx - hv.min()) / (hv.max() - hv.min() + 1e-6)) * 100))

                with st.expander(f"📈 Metrics: {selected_ticker}", expanded=True):
                    c1, c2, c3, c4, c5 = st.columns(5)
                    c1.metric("Price", f"${price:.2f}")
                    c2.metric(f"RSI", f"{rsi:.1f}")
                    c3.metric("Support", f"${sup:.2f}")
                    c4.metric("Resistance", f"${res:.2f}")
                    c5.metric("IVR", f"{ivr:.0f}%")

                with st.expander("📉 Price Chart & Payoff Diagram", expanded=True):
                    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
                    fig.add_trace(go.Scatter(x=hist.index, y=hist['Close'], name='Close', line=dict(color='blue')), row=1, col=1)
                    fig.add_trace(go.Scatter(x=hist.index, y=hist['Low'].rolling(support_window).min(), name='Support', line=dict(color='green', dash='dash')), row=1, col=1)
                    fig.add_trace(go.Scatter(x=hist.index, y=hist['High'].rolling(support_window).max(), name='Resistance', line=dict(color='red', dash='dash')), row=1, col=1)
                    
                    dp_rsi = hist['Close'].diff()
                    rsi_series = 100 - (100 / (1 + (dp_rsi.where(dp_rsi>0,0).rolling(rsi_window).mean() / -dp_rsi.where(dp_rsi<0,0).rolling(rsi_window).mean())))
                    fig.add_trace(go.Scatter(x=hist.index, y=rsi_series, name='RSI', line=dict(color='purple')), row=2, col=1)
                    fig.update_layout(height=350, margin=dict(l=5, r=5, t=5, b=5), template="plotly_white", legend=dict(orientation="h", y=1.02, x=1))
                    st.plotly_chart(fig, use_container_width=True)

                    # Expiration P&L Payoff Diagram for Short Put
                    st.markdown("##### 📊 Short Put Expiration P&L Payoff Diagram Simulation")
                    sim_strike = st.number_input("Simulation Strike", value=round(sup, 2))
                    sim_prem = st.number_input("Simulation Premium Received", value=1.50)
                    
                    x_range = [sim_strike * 0.8, sim_strike * 1.2]
                    prices_sim = [x_range[0] + i * (x_range[1] - x_range[0]) / 50 for i in range(51)]
                    pnl_sim = [(sim_prem - max(0, sim_strike - p)) * 100 for p in prices_sim]
                    
                    payoff_fig = go.Figure()
                    payoff_fig.add_trace(go.Scatter(x=prices_sim, y=pnl_sim, mode='lines', name='P&L at Expiry', line=dict(color='green', width=2)))
                    payoff_fig.add_hline(y=0, line_dash="dash", line_color="gray")
                    payoff_fig.update_layout(height=250, margin=dict(l=5, r=5, t=5, b=5), template="plotly_white", xaxis_title="Stock Price at Expiry ($)", yaxis_title="Profit / Loss ($)")
                    st.plotly_chart(payoff_fig, use_container_width=True)

                with st.expander("📊 Options Chain & Sizing", expanded=True):
                    try:
                        exps = stk.options
                        if exps:
                            t_date = st.selectbox("Expiry", exps)
                            puts = stk.option_chain(t_date).puts
                            if not puts.empty:
                                dte = max(1, (datetime.strptime(t_date, "%Y-%m-%d").date() - date.today()).days)
                                otm = puts[puts['strike'] < sup].copy()
                                if otm.empty: otm = puts[puts['strike'] < price * 0.95].copy()
                                if otm.empty: otm = puts.copy()
                                
                                otm['Delta'], _, _, otm['PoP_%'] = zip(*[calculate_greeks(price, r['strike'], dte, r.get('impliedVolatility', 0.3), "Put") for _, r in otm.iterrows()])
                                otm['Yield_%'] = (otm['bid'] / otm['strike']) * 100
                                max_c = account_size * (max_risk_pct / 100.0)
                                otm['Contracts'] = (max_c / (otm['strike'] * 100)).astype(int)
                                otm['Collateral'] = otm['strike'] * otm['Contracts'] * 100
                                
                                cols = ['strike', 'bid', 'ask', 'impliedVolatility', 'Delta', 'PoP_%', 'Yield_%', 'Contracts', 'Collateral']
                                st.dataframe(otm[cols].sort_values(by='bid', ascending=False), use_container_width=True)
                    except Exception as e:
                        st.warning(f"Chain error: {e}")

                with st.expander("📝 Log Trade to Google Sheets", expanded=False):
                    with st.form("j_form"):
                        sh_title = st.text_input("Sheet Title", value="options_trading_tracker-v5")
                        j1, j2, j3 = st.columns(3)
                        with j1:
                            tid = st.text_input("Trade ID", value="T-016")
                            strat = st.selectbox("Strategy", ["Cash-Secured Put", "Covered Call"])
                        with j2:
                            strike_in = st.number_input("Strike", value=round(sup, 2))
                            contr = st.number_input("Contracts", value=1, min_value=1)
                        with j3:
                            prem_in = st.number_input("Premium", value=1.50)
                            notes = st.text_input("Notes", value="Workstation log")
                        
                        if st.form_submit_button("🚀 Push to Sheet"):
                            row = [tid, str(date.today()), selected_ticker, strat, "Put", f"${strike_in:.2f}", str(date.today()), "30", str(contr), f"${prem_in:.2f}", f"${prem_in*contr*100:.2f}", f"${strike_in*contr*100:,.2f}", "$0.01", f"${price:.2f}", "0.30", f"{rsi:.1f}%", f"RSI support", "", "Open", "", "", "", "", "", "", notes]
                            ok, msg = log_trade(sh_title, row)
                            if ok: st.success(msg)
                            else: st.error(msg)
    else:
        st.info("👈 Select your ticker in the sidebar and click **Run Scan / Refresh**.")
