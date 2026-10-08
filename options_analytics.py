"""Pure calculation functions for the PowerX options workstation.

Greeks conventions:
- delta: change in option value per $1 move in underlying, per share
- theta: change in option value per calendar day, per share
- vega: change in option value per 1 volatility percentage point, per share
- gamma: change in delta per $1 move in underlying, per share
All Greeks are theoretical Black-Scholes estimates for European options.
American-style equity options, dividends, early exercise, and discrete dividends
are not modeled. Treat outputs as estimates, not executable trading advice.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from scipy.stats import norm

OptionType = Literal["Call", "Put"]
PositionSide = Literal["Long", "Short"]


@dataclass(frozen=True)
class Greeks:
    delta: float
    theta: float
    vega: float
    gamma: float


def calculate_greeks(
    spot: float,
    strike: float,
    dte: int,
    iv: float,
    option_type: OptionType = "Put",
    risk_free_rate: float = 0.045,
    dividend_yield: float = 0.0,
) -> Greeks:
    """Return Black-Scholes Greeks per share; IV is decimal (e.g. .30)."""
    if spot <= 0 or strike <= 0:
        raise ValueError("Spot and strike must be positive.")
    if dte <= 0:
        raise ValueError("Greeks are not calculated for expired/expiration-day options.")
    if iv <= 0 or not math.isfinite(iv):
        raise ValueError("Implied volatility must be positive and finite.")
    if option_type not in ("Call", "Put"):
        raise ValueError("option_type must be 'Call' or 'Put'.")

    t = dte / 365.0
    sqrt_t = math.sqrt(t)
    d1 = (
        math.log(spot / strike)
        + (risk_free_rate - dividend_yield + 0.5 * iv * iv) * t
    ) / (iv * sqrt_t)
    d2 = d1 - iv * sqrt_t
    pdf = norm.pdf(d1)
    discount_r = math.exp(-risk_free_rate * t)
    discount_q = math.exp(-dividend_yield * t)

    if option_type == "Call":
        delta = discount_q * norm.cdf(d1)
        theta_annual = (
            -(spot * discount_q * pdf * iv) / (2 * sqrt_t)
            - risk_free_rate * strike * discount_r * norm.cdf(d2)
            + dividend_yield * spot * discount_q * norm.cdf(d1)
        )
    else:
        delta = discount_q * (norm.cdf(d1) - 1.0)
        theta_annual = (
            -(spot * discount_q * pdf * iv) / (2 * sqrt_t)
            + risk_free_rate * strike * discount_r * norm.cdf(-d2)
            - dividend_yield * spot * discount_q * norm.cdf(-d1)
        )

    gamma = discount_q * pdf / (spot * iv * sqrt_t)
    vega_per_vol_point = spot * discount_q * pdf * sqrt_t / 100.0
    return Greeks(
        delta=float(delta),
        theta=float(theta_annual / 365.0),
        vega=float(vega_per_vol_point),
        gamma=float(gamma),
    )


def signed_position_greeks(
    greeks: Greeks, contracts: int, side: PositionSide, multiplier: int = 100
) -> dict[str, float]:
    """Aggregate a position's Greeks; long is positive quantity, short negative."""
    if contracts < 0:
        raise ValueError("Contracts cannot be negative.")
    if side not in ("Long", "Short"):
        raise ValueError("side must be 'Long' or 'Short'.")
    signed_qty = contracts * multiplier * (1 if side == "Long" else -1)
    return {
        "delta": greeks.delta * signed_qty,
        "theta": greeks.theta * signed_qty,
        "vega": greeks.vega * signed_qty,
        "gamma": greeks.gamma * signed_qty,
    }


def cash_secured_put_collateral(strike: float, contracts: int, multiplier: int = 100) -> float:
    if strike <= 0 or contracts < 0:
        raise ValueError("Strike must be positive and contracts cannot be negative.")
    return strike * contracts * multiplier


def covered_call_shares_required(contracts: int, multiplier: int = 100) -> int:
    if contracts < 0:
        raise ValueError("Contracts cannot be negative.")
    return contracts * multiplier


def contracts_within_budget(budget: float, strike: float, multiplier: int = 100) -> int:
    """Maximum whole CSP contracts fitting a collateral budget."""
    if budget < 0 or strike <= 0:
        raise ValueError("Budget must be nonnegative and strike must be positive.")
    return max(0, int(budget // (strike * multiplier)))


def short_put_expiration_pnl(
    stock_price_at_expiry: float, strike: float, premium_per_share: float,
    contracts: int = 1, multiplier: int = 100
) -> float:
    """P&L at expiry for a short put, before fees and assignment-related costs."""
    if min(stock_price_at_expiry, strike) < 0 or premium_per_share < 0 or contracts < 0:
        raise ValueError("Prices, premium, and contracts must be nonnegative.")
    intrinsic = max(0.0, strike - stock_price_at_expiry)
    return (premium_per_share - intrinsic) * contracts * multiplier


def short_call_expiration_pnl(
    stock_price_at_expiry: float, strike: float, premium_per_share: float,
    contracts: int = 1, multiplier: int = 100
) -> float:
    """P&L at expiry for a short call, before fees; excludes stock position P&L."""
    if min(stock_price_at_expiry, strike) < 0 or premium_per_share < 0 or contracts < 0:
        raise ValueError("Prices, premium, and contracts must be nonnegative.")
    intrinsic = max(0.0, stock_price_at_expiry - strike)
    return (premium_per_share - intrinsic) * contracts * multiplier


def option_midpoint(bid: float, ask: float) -> float | None:
    """Return a usable midpoint; reject crossed, negative, or missing quotes."""
    if not math.isfinite(bid) or not math.isfinite(ask) or bid < 0 or ask < 0 or ask < bid:
        return None
    if bid == 0 and ask == 0:
        return None
    return (bid + ask) / 2.0


def iv_rank(current_iv: float, historical_ivs: list[float]) -> float | None:
    """IV rank on a 0-100 scale from actual comparable IV observations."""
    values = [float(x) for x in historical_ivs if math.isfinite(float(x))]
    if not values:
        return None
    low, high = min(values), max(values)
    if high == low:
        return None
    return max(0.0, min(100.0, 100.0 * (current_iv - low) / (high - low)))


def relative_historical_volatility(current_hv: float, hv_history: list[float]) -> float | None:
    """Relative position of realized volatility; intentionally not labeled IV rank."""
    values = [float(x) for x in hv_history if math.isfinite(float(x))]
    if not values:
        return None
    low, high = min(values), max(values)
    if high == low:
        return None
    return max(0.0, min(100.0, 100.0 * (current_hv - low) / (high - low)))


def roll_cashflow(new_credit: float, close_debit: float, contracts: int = 1,
                  multiplier: int = 100, fees: float = 0.0) -> float:
    """Incremental roll cash flow; positive means net credit, before other tax effects."""
    if min(new_credit, close_debit, fees) < 0 or contracts < 0:
        raise ValueError("Credits, debits, fees, and contracts must be nonnegative.")
    return (new_credit - close_debit) * contracts * multiplier - fees
