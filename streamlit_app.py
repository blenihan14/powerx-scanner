import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, date

# Page Configuration
st.set_page_config(page_title="PowerX Pro Ultimate Scanner", layout="wide")

st.title("⚡ PowerX Pro Ultimate Options Scanner & Risk Engine")
st.markdown("Advanced quantitative screening, risk sizing, earnings blockers, stress testing, and webhook alerts.")

# ==========================================
# SIDEBAR: CONFIGURATION & RISK SETTINGS
# ==========================================
st.sidebar.header("⚙️ Account & Risk Parameters")
account_size = st.sidebar.number_input("Total Account Size ($)", min_value=1000.0, value=50000.0, step=1000.0)
max_risk_pct = st.sidebar.slider("Max Capital Allocation per Trade (%)", min_value=1.0, max_value=25.0, value=10.0, step=1.0)

st.sidebar.header("🔔 Webhook Alerts")
notification_type = st.sidebar.selectbox("Alert Platform", ["None", "Discord Webhook", "Telegram Bot"])
webhook_url = st.sidebar.text_input("Webhook URL / API Endpoint", type="password")

WATCHLIST = ["VTI", "MU", "VOO", "MO", "HD", "AAPL", "NVDA"]
selected_ticker = st.sidebar.selectbox("Select Watchlist Asset", WATCHLIST)

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

# Session State to prevent screen wipe on slider adjustments
if "scanned" not in st.session_state:
    st.session_state.scanned = False

if st.sidebar.button("Run Ultimate Scan", type="primary"):
    st.session_state.scanned = True

if st.session_state.scanned:
    with st.spinner(f"Running deep quantitative analysis on {selected_ticker}..."):
        stock = yf.Ticker(selected_ticker)
        hist = stock.history(period="6mo")
        
        if hist.empty:
            st.error(f"Could not retrieve historical data for {selected_ticker}.")
        else:
            # 1. Technical Indicators
            current_price = hist['Close'].iloc[-1]
            delta = hist['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            hist['RSI'] = 100 - (100 / (1 + rs))
            
            hist['Support'] = hist['Low'].rolling(window=20).min()
            hist['Resistance'] = hist['High'].rolling(window=20).max()
            
            current_rsi = hist['RSI'].iloc[-1]
            support_level = hist['Support'].iloc[-1]
            resistance_level = hist['Resistance'].iloc[-1]
            
            # 2. Earnings Catalyst Check
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

            # Display Metrics Dashboard
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Live Market Price", f"${current_price:.2f}")
            col2.metric("RSI (14)", f"{current_rsi:.2f}")
            col3.metric("20D Support Floor", f"${support_level:.2f}")
            col4.metric("20D Resistance Ceiling", f"${resistance_level:.2f}")
            
            if earnings_warning:
                st.error("🚨 **EARNINGS CATALYST WARNING**: This asset reports earnings within the next 14 days. Avoid selling naked options through binary events!")

            # Setup Evaluation
            near_support = current_price <= (support_level * 1.03)
            rsi_pullback = 30 <= current_rsi <= 55
            
            if near_support and rsi_pullback and not earnings_warning:
                pass_msg = f"🟢 **Setup PASSED**: {selected_ticker} is testing support with clean pullback momentum."
                st.success(pass_msg)
                if notification_type != "None" and webhook_url:
                    send_webhook_alert(webhook_url, f"PowerX Alert: {pass_msg} Price: ${current_price:.2f}")
            else:
                st.warning("🟡 **Setup WATCH**: Technical criteria not fully aligned or blocked by upcoming earnings.")
            
            # 3. Options Chain & Position Sizing Calculator
            st.subheader("📊 Options Chain & Position Sizing Calculator")
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

            # 4. Interactive What-If Stress Tester (Persistent via Session State)
            st.subheader("🧪 Interactive 'What-If' Stress Tester (Short Put Simulation)")
            st.caption("Simulate adverse market moves on your portfolio risk.")
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                sim_drop = st.slider("Simulate Stock Price Drop (%)", 0.0, 30.0, 10.0, 1.0)
            with col_s2:
                sim_iv_spike = st.slider("Simulate IV Spike (%)", 0.0, 100.0, 20.0, 5.0)
                
            sim_stock_price = current_price * (1 - (sim_drop / 100.0))
            st.info(f"If {selected_ticker} drops by {sim_drop}% to **${sim_stock_price:.2f}** with a {sim_iv_spike}% IV spike, short put option values will expand, requiring active management (rolling or assignment).")
else:
    st.info("👈 Select your ticker in the sidebar and click **Run Ultimate Scan** to begin.")
