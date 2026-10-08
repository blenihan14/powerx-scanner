"""Market-data helpers for the PowerX Options Workstation.

Uses Yahoo Finance through yfinance. Yahoo can rate-limit or reject requests;
these helpers fail gracefully so the Streamlit app can show an unavailable-data
message instead of crashing. Quotes and option chains should be verified with a
broker before making any decision.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def _empty_history() -> pd.DataFrame:
    frame = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Adj Close", "Volume"])
    frame.index = pd.DatetimeIndex([], name="Date")
    return frame


def _valid_symbol(symbol: str) -> str:
    symbol = str(symbol or "").strip().upper()
    if not symbol or len(symbol) > 20 or not all(c.isalnum() or c in ".-^=" for c in symbol):
        raise ValueError("Invalid ticker symbol")
    return symbol


def get_history(ticker: str, period: str = "6mo") -> pd.DataFrame:
    """Return historical OHLCV data indexed by date, or an empty frame on failure."""
    symbol = _valid_symbol(ticker)
    allowed_periods = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}
    if period not in allowed_periods:
        raise ValueError(f"Unsupported history period: {period}")
    try:
        data = yf.Ticker(symbol).history(period=period, auto_adjust=False, timeout=20)
        if data is None or data.empty:
            logger.warning("Yahoo Finance returned no historical data for %s", symbol)
            return _empty_history()
        data = data.copy()
        # Some feeds may omit these columns; ensure the app can safely check them.
        for column in ("Open", "High", "Low", "Close", "Adj Close", "Volume"):
            if column not in data.columns:
                data[column] = pd.NA
        return data.sort_index()
    except Exception:
        logger.exception("Historical data request failed for %s", symbol)
        return _empty_history()


def get_expirations(ticker: str) -> list[str]:
    """Return option expiration dates as YYYY-MM-DD strings."""
    symbol = _valid_symbol(ticker)
    try:
        expirations = yf.Ticker(symbol).options
        return [str(value) for value in expirations] if expirations else []
    except Exception:
        logger.exception("Could not retrieve option expirations for %s", symbol)
        return []


def get_option_chain(ticker: str, expiration: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (calls, puts) DataFrames for an expiration date."""
    symbol = _valid_symbol(ticker)
    empty = pd.DataFrame(columns=[
        "contractSymbol", "strike", "lastPrice", "bid", "ask", "change",
        "percentChange", "volume", "openInterest", "impliedVolatility",
    ])
    try:
        exp = datetime.strptime(str(expiration), "%Y-%m-%d").date()
        if exp < date.today():
            return empty.copy(), empty.copy()
        chain = yf.Ticker(symbol).option_chain(exp.isoformat())
        calls = chain.calls.copy() if chain and chain.calls is not None else empty.copy()
        puts = chain.puts.copy() if chain and chain.puts is not None else empty.copy()
        return calls, puts
    except Exception:
        logger.exception("Could not retrieve option chain for %s expiring %s", symbol, expiration)
        return empty.copy(), empty.copy()


def get_vix() -> Optional[float]:
    """Return latest available VIX close, or None if unavailable."""
    try:
        history = get_history("^VIX", "5d")
        if history.empty or "Close" not in history:
            return None
        close = pd.to_numeric(history["Close"], errors="coerce").dropna()
        return float(close.iloc[-1]) if not close.empty else None
    except Exception:
        logger.exception("Could not retrieve VIX")
        return None


def next_earnings_date(ticker: str) -> Optional[date]:
    """Return the next reported earnings date, or None when Yahoo has none."""
    symbol = _valid_symbol(ticker)
    try:
        calendar = yf.Ticker(symbol).calendar
        if calendar is None or getattr(calendar, "empty", False):
            return None
        # Recent yfinance versions commonly return a DataFrame with an
        # Earnings Date row; older versions may return a dict-like object.
        values = None
        if isinstance(calendar, pd.DataFrame):
            if "Earnings Date" in calendar.index:
                values = calendar.loc["Earnings Date"].tolist()
            elif "Earnings Date" in calendar.columns:
                values = calendar["Earnings Date"].tolist()
        elif isinstance(calendar, dict):
            values = calendar.get("Earnings Date")
        if values is None:
            return None
        if not isinstance(values, (list, tuple, pd.Series)):
            values = [values]
        candidates: list[date] = []
        for value in values:
            if value is None or pd.isna(value):
                continue
            parsed = pd.to_datetime(value, errors="coerce")
            if pd.isna(parsed):
                continue
            candidates.append(parsed.date())
        future = [item for item in candidates if item >= date.today()]
        return min(future) if future else None
    except Exception:
        logger.exception("Could not retrieve earnings date for %s", symbol)
        return None


def option_midpoint_column(chain: pd.DataFrame) -> pd.Series:
    """Compute a usable midpoint from bid/ask, falling back to lastPrice."""
    if chain is None or chain.empty:
        return pd.Series(dtype="float64", index=getattr(chain, "index", None), name="Mid")
    bid = pd.to_numeric(chain.get("bid", pd.Series(index=chain.index, dtype="float64")), errors="coerce")
    ask = pd.to_numeric(chain.get("ask", pd.Series(index=chain.index, dtype="float64")), errors="coerce")
    last = pd.to_numeric(chain.get("lastPrice", pd.Series(index=chain.index, dtype="float64")), errors="coerce")
    valid_quote = bid.notna() & ask.notna() & (bid >= 0) & (ask >= bid) & ((bid > 0) | (ask > 0))
    midpoint = ((bid + ask) / 2).where(valid_quote)
    return midpoint.fillna(last.where(last >= 0)).rename("Mid")
