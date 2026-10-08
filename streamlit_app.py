import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, date

# Page Configuration
st.set_page_config(page_title="PowerX Pro Ultimate Scanner", layout="wide")

st.title("⚡ PowerX Pro Ultimate Options Scanner & Risk Engine")
st.markdown("Modular quantitative screening, risk sizing, earnings blockers, stress testing, and collapsible feature blocks.")

# ==========================================
# SIDEBAR: COLLAPSIBLE CONFIGURATION SECTIONS
# ==========================================
st.sidebar.header("⚙️ Control Panel")

with st.sidebar.expander("💰 Account & Risk Parameters", expanded=True):
    account_size = st.number_input("Total Account Size ($)", min_value=1000.0, value=50000.0, step=1000.0)
    max_risk_pct = st.slider("Max Capital Allocation per Trade (%)", min_value=1.0, max_value=25.0, value=10.0, step=1.0)

with st.sidebar.expander("🎛️ Technical Indicator Settings", expanded=False):
    hist_period = st.selectbox("Historical Data Period", ["3mo", "6mo", "1y", "2y"], index=1)
    rsi_window = st.slider("RSI Lookback Period", min_value=5, max_value=30, value=14, step=1)
    support_window = st.slider("Support/Resistance Window (Days)", min_value=10, max_value=100, value=20, step=5)

with st.sidebar.expander("🔍 Scanner Mode & Watchlist", expanded=True):
    scan_mode = st.radio("Select Mode", ["Single Ticker Deep Dive", "⚡ Batch Market Screener (All Watchlist)"])
    DEFAULT_WATCHLIST = ["VTI", "VOO", "SPY", "QQQ", "MU", "MO", "HD", "AAPL", "NVDA", "TSLA", "AMD"]
    custom_ticker_input = st.text_input("Add Custom Ticker", "").upper().strip()
    if custom_ticker_input and custom_ticker_input not in DEFAULT_WATCHLIST:
        DEFAULT_WATCHLIST.append(custom_ticker_input)
    selected_ticker = st.selectbox("Select Target Ticker (Single Mode)", DEFAULT_WATCHLIST)

with st.sidebar.expander("🔔 Webhook Alerts", expanded=False):
    notification_type = st.selectbox("Alert Platform", ["None", "Discord Webhook", "Telegram Bot"])
    webhook_url = st.text_input("Webhook URL / API Endpoint", type="password")

def send_webhook_alert(url, message):
    if not url:
        return False
    try:
        if "discord" in url:
            response = requests.post(url, json={"content": message})
            return response.status_code == 204
        elif "telegram" in url:
            response = requests.get(url)
            return response.status_code == 200
    except Exception as e:
        st.sidebar.error(f"Alert failed: {e}")
    return False

if "scanned" not in st.session_state:
    st.session_state.scanned = False

if st.sidebar.button("Run Ultimate Scan", type="primary"):
    st.session_state.scanned = True

# ==========================================
# MODE 1: BATCH MARKET SCREENER
# ==========================================
if scan_mode == "⚡ Batch Market Screener (All Watchlist)":
    st.subheader("🌐 Automated Watchlist Screener")
    st.markdown(f"Scanning all watchlist assets simultaneously using a **{hist_period}** timeframe, **RSI ({rsi_window})**, and **{support_window}-day** support windows.")
    
    if st.button("Run Full Batch Scan Now", type="primary"):
        results = []
        progress_bar = st.progress(0)
        total_tickers = len(DEFAULT_WATCHLIST)
        
        for idx, ticker in enumerate(DEFAULT_WATCHLIST):
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period=hist_period)
                if not hist.empty and len(hist) >= support_window:
                    price = hist['Close'].iloc[-1]
                    delta = hist['Close'].diff()
                    gain = (delta.where(delta > 0, 0)).rolling(window=rsi_window).mean()
                    loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_window).mean()
                    rs = gain / loss
                    rsi = 100 - (100 / (1 + rs))
                    current_rsi = rsi.iloc[-1]
                    
                    support = hist['Low'].rolling(window=support_window).min().iloc[-1]
                    
                    earnings_block = False
                    try:
                        cal = stock.calendar
                        if cal and 'Earnings Date' in cal:
                            next_earn = pd.to_datetime(cal['Earnings Date'][0]).date()
                            if 0 <= (next_earn - date.today()).days <= 14:
                                earnings_block = True
                    except:
                        pass
                    
                    near_sup = price <= (support * 1.03)
                    pullback_ok = 30 <= current_rsi <= 55
                    
                    status = "Watching"
                    if near_sup and pullback_ok and not earnings_block:
                        status = "✅ PASS (Setup Active)"
                    elif earnings_block:
                        status = "⚠️ Earnings Block"
                        
                    results.append({
                        "Ticker": ticker,
                        "Price": round(price, 2),
                        f"RSI ({rsi_window})": round(current_rsi, 2),
                        f"{support_window}D Support Floor": round(support, 2),
                        "Earnings Risk": "Yes" if earnings_block else "Clear",
                        "Scan Status": status
                    })
            except Exception:
                pass
            progress_bar.progress((idx + 1) / total_tickers)
            
        if results:
            df_results = pd.DataFrame(results)
            st.dataframe(df_results, use_container_width=True)
            
            passed_df = df_results[df_results["Scan Status"].str.contains("PASS")]
            if not passed_df.empty:
                st.success(f"Found {len(passed_df)} qualifying asset(s) ready for review!")
            else:
                st.info("No assets currently match the strict criteria on this timeframe.")

# ==========================================
# MODE 2: SINGLE TICKER DEEP DIVE WITH EXPANDERS
# ==========================================
elif scan_mode == "Single Ticker Deep Dive":
    if st.session_state.scanned:
        with st.spinner(f"Running deep quantitative analysis on {selected_ticker} ({hist_period})..."):
            stock = yf.Ticker(selected_ticker)
            hist = stock.history(period=hist_period)
            
            if hist.empty or len(hist) < support_window:
                st.error(f"Insufficient historical data retrieved for {selected_ticker} using period {hist_period}.")
            else:
                current_price = hist['Close'].iloc[-1]
                delta = hist['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=rsi_window).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_window).mean()
                rs = gain / loss
                hist['RSI'] = 100 - (100 / (1 + rs))
                
                hist['Support'] = hist['Low'].rolling(window=support_window).min()
                hist['Resistance'] = hist['High'].rolling(window=support_window).max()
                
                current_rsi = hist['RSI'].iloc[-1]
                support_level = hist['Support'].iloc[-1]
                resistance_level = hist['Resistance'].iloc[-1]
                
                earnings_warning = False
                try:
                    calendar = stock.calendar
                    if calendar and 'Earnings Date' in calendar:
                        next_earnings = pd.to_datetime(calendar['Earnings Date'][0]).date()
                        days_to_earnings = (next_earnings - date.today()).days
                        if 0 <= days_to_earnings <= 14:
                            earnings_warning = True
                except:
                    pass

                # Section 1: Technical Metrics & Status (Collapsible)
                with st.expander(f"📈 Technical Indicators & Metrics: {selected_ticker}", expanded=True):
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Live Market Price", f"${current_price:.2f}")
                    col2.metric(f"RSI ({rsi_window})", f"{current_rsi:.2f}")
                    col3.metric(f"{support_window}D Support Floor", f"${support_level:.2f}")
                    col4.metric(f"{support_window}D Resistance Ceiling", f"${resistance_level:.2f}")
                    
                    if earnings_warning:
                        st.error("🚨 **EARNINGS CATALYST WARNING**: This asset reports earnings within the next 14 days. Avoid selling options through binary events!")

                    near_support = current_price <= (support_level * 1.03)
                    rsi_pullback = 30 <= current_rsi <= 55
                    
                    if near_support and rsi_pullback and not earnings_warning:
                        pass_msg = f"🟢 **Setup PASSED**: {selected_ticker} is testing support with clean pullback momentum."
                        st.success(pass_msg)
                        if notification_type != "None" and webhook_url:
                            send_webhook_alert(webhook_url, f"PowerX Alert: {pass_msg} Price: ${current_price:.2f}")
                    else:
                        st.warning("🟡 **Setup WATCH**: Technical criteria not fully aligned or blocked by upcoming earnings.")

                # Section 2: Options Chain & Position Sizing Calculator (Collapsible)
                with st.expander("📊 Options Chain & Position Sizing Calculator", expanded=True):
                    try:
                        exp_dates = stock.options
                        if exp_dates and len(exp_dates) > 0:
                            target_date = exp_dates[0]
                            opt_chain = stock.option_chain(target_date)
                            puts = opt_chain.puts
                            
                            if not puts.empty:
                                otm_puts = puts[puts['strike'] < support_level].copy()
                                if otm_puts.empty:
                                    otm_puts = puts[puts['strike'] < current_price * 0.95].copy()
                                if otm_puts.empty:
                                    otm_puts = puts.copy()
                                    
                                otm_puts['Yield_%'] = (otm_puts['bid'] / otm_puts['strike']) * 100
                                max_capital_allowed = account_size * (max_risk_pct / 100.0)
                                otm_puts['Max_Contracts'] = (max_capital_allowed / (otm_puts['strike'] * 100)).astype(int)
                                otm_puts['Total_Collateral'] = otm_puts['strike'] * otm_puts['Max_Contracts'] * 100
                                otm_puts['Potential_Premium'] = otm_puts['bid'] * otm_puts['Max_Contracts'] * 100
                                
                                display_cols = ['strike', 'bid', 'ask', 'impliedVolatility', 'volume', 'Yield_%', 'Max_Contracts', 'Total_Collateral', 'Potential_Premium']
                                
                                st.caption(f"Calculated for max risk allocation: **${max_capital_allowed:,.2f}** ({max_risk_pct}% of account) | Expiry: {target_date}")
                                st.dataframe(
                                    otm_puts[display_cols].sort_values(by='bid', ascending=False),
                                    use_container_width=True
                                )
                            else:
                                st.info("Yahoo Finance returned an empty options chain for this ticker right now.")
                        else:
                            st.info("No active option expiration dates found via Yahoo Finance for this ticker.")
                    except Exception as e:
                        st.warning(f"Unable to fetch live options chain due to Yahoo Finance rate limits: {e}")

                # Section 3: Interactive What-If Stress Tester (Collapsible)
                with st.expander("🧪 Interactive 'What-If' Stress Tester (Short Put Simulation)", expanded=True):
                    st.caption("Simulate adverse market moves on your portfolio risk.")
                    col_s1, col_s2 = st.columns(2)
                    with col_s1:
                        sim_drop = st.slider("Simulate Stock Price Drop (%)", 0.0, 30.0, 10.0, 1.0, key="sim_drop_slider")
                    with col_s2:
                        sim_iv_spike = st.slider("Simulate IV Spike (%)", 0.0, 100.0, 20.0, 5.0, key="sim_iv_slider")
                        
                    sim_stock_price = current_price * (1 - (sim_drop / 100.0))
                    st.info(f"If {selected_ticker} drops by {sim_drop}% to **${sim_stock_price:.2f}** with a {sim_iv_spike}% IV spike, short put option values will expand, requiring active management (rolling or assignment).")
    else:
        st.info("👈 Select your ticker in the sidebar and click **Run Ultimate Scan** to begin deep dive mode.")
