from __future__ import annotations

import logging
import math
from datetime import date, datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from options_analytics import (
    calculate_greeks, signed_position_greeks, cash_secured_put_collateral,
    covered_call_shares_required, contracts_within_budget,
    short_put_expiration_pnl, option_midpoint, relative_historical_volatility,
    roll_cashflow,
)
from market_data import (
    get_history, get_expirations, get_option_chain, get_vix,
    next_earnings_date, option_midpoint_column,
)
from journal import get_records, append_trade

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="PowerX Options Workstation",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.title("⚡ PowerX Options Workstation")
st.caption(
    "Personal research tool for options analysis. Quotes may be delayed or incomplete. "
    "Greeks are theoretical estimates; verify all quotes and orders with your broker."
)

with st.sidebar:
    st.header("Control Panel")
    vix = get_vix()
    if vix is None:
        st.caption("VIX: unavailable")
    else:
        label = "Low" if vix < 15 else ("Normal" if vix <= 25 else "High")
        st.metric("VIX (latest available close)", f"{vix:.2f}", label)

    account_size = st.number_input("Account value ($)", min_value=0.0, value=50000.0, step=1000.0)
    max_trade_pct = st.slider("Maximum CSP collateral budget (% of account)", 1, 100, 10)
    hist_period = st.selectbox("Historical period", ["3mo", "6mo", "1y", "2y"], index=1)
    rsi_window = st.slider("RSI window", 5, 30, 14)
    support_window = st.slider("Support window (trading days)", 10, 100, 20)
    ticker = st.text_input("Ticker", value="VTI").strip().upper()
    mode = st.radio(
        "Workspace",
        ["Ticker Analysis", "Option Chain & Sizing", "Portfolio Greeks & Journal",
         "Roll Simulator", "Stock Signal Study"],
    )
    if st.button("Clear cached market data"):
        st.cache_data.clear()
        st.rerun()


def calculate_rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / avg_loss
    result = 100 - 100 / (1 + rs)
    result = result.mask((avg_loss == 0) & (avg_gain > 0), 100)
    result = result.mask((avg_gain == 0) & (avg_loss > 0), 0)
    result = result.mask((avg_gain == 0) & (avg_loss == 0), 50)
    return result


def validate_ticker(value: str) -> bool:
    return bool(value) and len(value) <= 15 and all(ch.isalnum() or ch in ".-^=" for ch in value)


if not validate_ticker(ticker):
    st.error("Enter a valid ticker symbol.")
    st.stop()

if mode == "Ticker Analysis":
    st.subheader(f"{ticker}: price, technicals, and volatility")
    try:
        hist = get_history(ticker, hist_period)
        if hist.empty or len(hist) < max(support_window, rsi_window + 2):
            st.warning("Not enough historical data for the selected settings.")
            st.stop()

        hist = hist.copy()
        hist["RSI"] = calculate_rsi(hist["Close"], rsi_window)
        hist["Support"] = hist["Low"].rolling(support_window).min()
        hist["Resistance"] = hist["High"].rolling(support_window).max()
        hv = hist["Close"].pct_change().rolling(20).std() * math.sqrt(252)
        hv_valid = hv.dropna()
        latest_hv = float(hv_valid.iloc[-1]) if not hv_valid.empty else float("nan")
        hv_rank = relative_historical_volatility(latest_hv, hv_valid.tolist()) if math.isfinite(latest_hv) else None

        latest = hist.iloc[-1]
        cols = st.columns(5)
        cols[0].metric("Latest close", f"${latest['Close']:.2f}")
        cols[1].metric("RSI", "—" if pd.isna(latest["RSI"]) else f"{latest['RSI']:.1f}")
        cols[2].metric("Rolling support", "—" if pd.isna(latest["Support"]) else f"${latest['Support']:.2f}")
        cols[3].metric("Rolling resistance", "—" if pd.isna(latest["Resistance"]) else f"${latest['Resistance']:.2f}")
        cols[4].metric("Relative historical vol.", "—" if hv_rank is None else f"{hv_rank:.0f}/100")

        st.caption("Relative historical volatility is based on realized volatility; it is not IV rank.")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=hist.index, y=hist["Close"], name="Close"))
        fig.add_trace(go.Scatter(x=hist.index, y=hist["Support"], name="Rolling support", line=dict(dash="dash")))
        fig.add_trace(go.Scatter(x=hist.index, y=hist["Resistance"], name="Rolling resistance", line=dict(dash="dash")))
        fig.update_layout(height=450, xaxis_title="Date", yaxis_title="Price ($)", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

        rsi_fig = go.Figure(go.Scatter(x=hist.index, y=hist["RSI"], name="RSI"))
        rsi_fig.add_hline(y=30, line_dash="dash")
        rsi_fig.add_hline(y=70, line_dash="dash")
        rsi_fig.update_layout(height=220, yaxis_range=[0, 100])
        st.plotly_chart(rsi_fig, use_container_width=True)
        earnings = next_earnings_date(ticker)
        st.info(f"Next earnings date: {earnings.isoformat()}" if earnings else "Earnings date unavailable from Yahoo Finance.")
    except Exception as exc:
        logger.exception("Ticker analysis failed")
        st.error(f"Could not analyze {ticker}: {exc}")

elif mode == "Option Chain & Sizing":
    st.subheader(f"{ticker}: option chain and cash-secured put sizing")
    try:
        hist = get_history(ticker, "5d")
        if hist.empty:
            st.error("Underlying price unavailable.")
            st.stop()
        spot = float(hist["Close"].dropna().iloc[-1])
        expirations = get_expirations(ticker)
        if not expirations:
            st.warning("No option expirations were returned.")
            st.stop()

        expiry = st.selectbox("Expiration", list(expirations))
        option_type = st.radio("Option type", ["Put", "Call"], horizontal=True)
        calls, puts = get_option_chain(ticker, expiry)
        chain = puts if option_type == "Put" else calls
        if chain.empty:
            st.warning("No contracts returned for this expiration.")
            st.stop()

        expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
        dte = (expiry_date - date.today()).days
        if dte <= 0:
            st.warning("Expiration is today or in the past; theoretical Greeks are omitted.")
        earnings = next_earnings_date(ticker)
        if earnings and date.today() <= earnings <= expiry_date:
            st.warning(f"Earnings may occur before this expiration ({earnings}). Verify the date.")

        chain = chain.copy()
        chain["Mid"] = option_midpoint_column(chain)
        budget = account_size * max_trade_pct / 100.0
        rows = []
        for _, row in chain.iterrows():
            strike = float(row["strike"])
            bid = float(row.get("bid", 0) or 0)
            ask = float(row.get("ask", 0) or 0)
            mid = row["Mid"]
            iv = float(row.get("impliedVolatility", 0) or 0)
            try:
                g = calculate_greeks(spot, strike, dte, iv, option_type) if dte > 0 and iv > 0 else None
            except (ValueError, OverflowError):
                g = None

            if option_type == "Put":
                contracts = contracts_within_budget(budget, strike)
                collateral = cash_secured_put_collateral(strike, contracts)
                breakeven = strike - (float(mid) if pd.notna(mid) else 0.0)
                premium_pct = (float(mid) / strike * 100) if pd.notna(mid) and strike else float("nan")
            else:
                contracts = 0
                collateral = 0.0
                breakeven = strike + (float(mid) if pd.notna(mid) else 0.0)
                premium_pct = (float(mid) / spot * 100) if pd.notna(mid) and spot else float("nan")

            spread_pct = ((ask - bid) / float(mid) * 100) if pd.notna(mid) and float(mid) > 0 and ask >= bid else float("nan")
            rows.append({
                "Strike": strike, "Bid": bid, "Ask": ask, "Mid": mid,
                "Spread % of mid": spread_pct, "IV": iv,
                "Delta (theoretical)": g.delta if g else None,
                "Theta / day / share": g.theta if g else None,
                "Vega / vol point / share": g.vega if g else None,
                "Gamma / share": g.gamma if g else None,
                "Premium % reference": premium_pct,
                "Expiration breakeven": breakeven,
                "CSP contracts within budget": contracts if option_type == "Put" else "N/A",
                "CSP collateral": collateral if option_type == "Put" else "N/A",
                "Volume": row.get("volume", None), "Open interest": row.get("openInterest", None),
            })
        result = pd.DataFrame(rows)
        if option_type == "Put":
            result = result[result["Strike"] < spot].sort_values("Strike", ascending=False)
        else:
            result = result[result["Strike"] >= spot].sort_values("Strike")
        st.caption(
            f"Underlying latest available close: ${spot:.2f}. Budget: ${budget:,.0f}. "
            "CSP sizing reserves strike × 100 × contracts and does not imply suitability."
        )
        st.dataframe(result, use_container_width=True, hide_index=True)
        st.download_button(
            "Download option analysis CSV", result.to_csv(index=False).encode("utf-8"),
            f"{ticker}_{expiry}_{option_type.lower()}_analysis.csv", "text/csv"
        )
    except Exception as exc:
        logger.exception("Option chain analysis failed")
        st.error(f"Could not load option chain: {exc}")

elif mode == "Portfolio Greeks & Journal":
    st.subheader("Portfolio Greeks & Trade Journal")
    sheet_title = st.text_input("Google Sheet title", value="options_trading_tracker-v5")
    if st.button("Load open positions", type="primary"):
        try:
            records = get_records(sheet_title)
            df = pd.DataFrame(records)
            required = {"Ticker", "Strike", "Expiration", "Contracts", "Option Type", "Side", "Status"}
            missing = required - set(df.columns)
            if missing:
                st.error("Journal is missing required columns: " + ", ".join(sorted(missing)))
            else:
                open_df = df[df["Status"].astype(str).str.lower().eq("open")].copy()
                totals = {"delta": 0.0, "theta": 0.0, "vega": 0.0, "gamma": 0.0}
                detail = []
                for _, row in open_df.iterrows():
                    try:
                        symbol = str(row["Ticker"]).strip().upper()
                        strike = float(str(row["Strike"]).replace("$", "").replace(",", ""))
                        contracts = int(float(row["Contracts"]))
                        opt_type = str(row["Option Type"]).title()
                        side = str(row["Side"]).title()
                        expiry = pd.to_datetime(row["Expiration"]).date()
                        dte = (expiry - date.today()).days
                        if dte <= 0:
                            detail.append({"Ticker": symbol, "Warning": "Expired/expiration-day; Greeks omitted"})
                            continue
                        h = get_history(symbol, "5d")
                        if h.empty:
                            detail.append({"Ticker": symbol, "Warning": "Underlying price unavailable"})
                            continue
                        spot = float(h["Close"].dropna().iloc[-1])
                        iv_field = row.get("IV", None)
                        try:
                            iv = float(iv_field)
                            if iv > 1:
                                iv /= 100
                            if not math.isfinite(iv) or iv <= 0:
                                raise ValueError()
                        except (TypeError, ValueError):
                            detail.append({"Ticker": symbol, "Warning": "IV missing; position omitted from totals"})
                            continue
                        g = calculate_greeks(spot, strike, dte, iv, opt_type)
                        pos = signed_position_greeks(g, contracts, side)
                        for key in totals:
                            totals[key] += pos[key]
                        detail.append({
                            "Ticker": symbol, "Spot": spot, "Strike": strike, "DTE": dte,
                            "Option Type": opt_type, "Side": side, "Contracts": contracts,
                            "IV": iv, **pos, "Warning": "",
                        })
                    except Exception as exc:
                        logger.exception("Could not calculate Greeks for journal row")
                        detail.append({"Ticker": str(row.get("Ticker", "")), "Warning": str(exc)})

                metrics = st.columns(4)
                metrics[0].metric("Delta (share equivalent)", f"{totals['delta']:.1f}")
                metrics[1].metric("Theta ($/calendar day)", f"${totals['theta']:.2f}")
                metrics[2].metric("Vega ($/1 IV point)", f"${totals['vega']:.2f}")
                metrics[3].metric("Gamma (delta change / $1)", f"{totals['gamma']:.3f}")
                st.caption("Only positions with valid IV and unexpired options are included. Black-Scholes estimates do not model early exercise.")
                st.dataframe(pd.DataFrame(detail), use_container_width=True, hide_index=True)
                st.markdown("#### Journal records")
                st.dataframe(open_df, use_container_width=True, hide_index=True)
        except Exception as exc:
            logger.exception("Journal read failed")
            st.error(f"Could not load Google Sheet: {exc}")

    st.markdown("---")
    st.markdown("#### Log a trade")
    with st.form("trade_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            trade_id = st.text_input("Trade ID")
            trade_ticker = st.text_input("Ticker", value=ticker).strip().upper()
            strategy = st.selectbox("Strategy", ["Cash-Secured Put", "Covered Call", "Other"])
            option_type = st.selectbox("Option type", ["Put", "Call"])
        with c2:
            side = st.selectbox("Side", ["Short", "Long"])
            strike = st.number_input("Strike ($)", min_value=0.01, value=100.0)
            expiry = st.date_input("Expiration", value=date.today())
            contracts = st.number_input("Contracts", min_value=1, value=1, step=1)
        with c3:
            opened = st.date_input("Opened date", value=date.today())
            premium = st.number_input("Premium/debit per share ($)", min_value=0.0, value=1.0, step=0.05)
            underlying_entry = st.number_input("Underlying at entry ($)", min_value=0.0, value=100.0)
            iv_pct = st.number_input("Implied volatility (%)", min_value=0.1, max_value=500.0, value=30.0, step=1.0)
            status = st.selectbox("Status", ["Open", "Closed", "Assigned"])
        notes = st.text_input("Notes")
        submitted = st.form_submit_button("Save trade")
        if submitted:
            if not trade_id.strip() or not validate_ticker(trade_ticker):
                st.error("Trade ID and a valid ticker are required.")
            elif expiry < opened:
                st.error("Expiration cannot be before the opened date.")
            else:
                trade = {
                    "Trade ID": trade_id.strip(), "Opened Date": opened.isoformat(),
                    "Ticker": trade_ticker, "Strategy": strategy, "Option Type": option_type,
                    "Side": side, "Strike": strike, "Expiration": expiry.isoformat(),
                    "Contracts": int(contracts), "Premium Per Share": premium,
                    "Total Premium": premium * int(contracts) * 100 * (1 if side == "Short" else -1),
                    "Underlying At Entry": underlying_entry, "IV": iv_pct / 100.0,
                    "Status": status, "Notes": notes,
                }
                ok, message = append_trade(sheet_title, trade)
                (st.success if ok else st.error)(message)

elif mode == "Roll Simulator":
    st.subheader("Roll Simulator")
    c1, c2, c3 = st.columns(3)
    with c1:
        old_strike = st.number_input("Current strike ($)", min_value=0.01, value=150.0)
        close_debit = st.number_input("Cost to close per share ($)", min_value=0.0, value=0.50)
    with c2:
        new_strike = st.number_input("New strike ($)", min_value=0.01, value=145.0)
        new_credit = st.number_input("New credit per share ($)", min_value=0.0, value=2.20)
    with c3:
        contracts = st.number_input("Contracts", min_value=1, value=1, step=1)
        fees = st.number_input("Total fees ($)", min_value=0.0, value=0.0)
    cashflow = roll_cashflow(new_credit, close_debit, int(contracts), fees=fees)
    st.metric("Incremental roll cash flow", f"${cashflow:,.2f}", "Net credit" if cashflow >= 0 else "Net debit")
    st.write(f"Strike change: ${new_strike - old_strike:+.2f} per share.")
    st.caption("This is incremental cash flow only. It does not erase the old position's loss or calculate total trade P&L.")
    st.warning("Add old/new expiration, original premium, and underlying price before using this as a complete roll decision tool.")

elif mode == "Stock Signal Study":
    st.subheader("Stock pullback signal study (not an options backtest)")
    bt_ticker = st.text_input("Study ticker", value=ticker).strip().upper()
    years = st.selectbox("Historical span", ["1y", "2y", "5y"], index=1)
    if st.button("Run signal study", type="primary"):
        try:
            hist = get_history(bt_ticker, years)
            if hist.empty:
                st.error("No historical data returned.")
                st.stop()
            hist = hist.copy()
            hist["RSI"] = calculate_rsi(hist["Close"], 14)
            hist["Support"] = hist["Low"].rolling(20).min()
            # Use next session's close as a conservative, reproducible entry proxy.
            hist["Entry"] = hist["Close"].shift(-1)
            hist["Exit"] = hist["Close"].shift(-21)
            signals = hist[
                (hist["Close"] <= hist["Support"] * 1.03)
                & hist["RSI"].between(30, 55)
                & hist["Entry"].notna()
                & hist["Close"].shift(-20).notna()
            ].copy()
            signals["Exit Price"] = hist["Close"].shift(-20).reindex(signals.index)
            signals["Return %"] = (signals["Exit Price"] / signals["Entry"] - 1) * 100
            # De-overlap signals: keep a signal only if at least 20 sessions after prior accepted signal.
            accepted = []
            last_loc = -10_000
            locations = {idx: i for i, idx in enumerate(hist.index)}
            for idx, row in signals.iterrows():
                loc = locations[idx]
                if loc - last_loc >= 20:
                    accepted.append((idx, row))
                    last_loc = loc
            result = pd.DataFrame([row for _, row in accepted])
            if result.empty:
                st.info("No qualifying signals with a full forward window.")
            else:
                win_rate = (result["Return %"] > 0).mean() * 100
                avg_return = result["Return %"].mean()
                st.metric("Non-overlapping signals", len(result))
                c1, c2 = st.columns(2)
                c1.metric("Positive 20-session outcomes", f"{win_rate:.1f}%")
                c2.metric("Average 20-session return", f"{avg_return:.2f}%")
                st.dataframe(result[["Close", "RSI", "Support", "Entry", "Exit Price", "Return %"]], use_container_width=True)
                st.download_button("Download signal study CSV", result.to_csv(index=False).encode("utf-8"), "stock_signal_study.csv", "text/csv")
            st.caption("Exploratory stock-price study only. It does not model options, fees, taxes, or a tradable portfolio.")
        except Exception as exc:
            logger.exception("Signal study failed")
            st.error(f"Study failed: {exc}")
