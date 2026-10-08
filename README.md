PowerX Options Workstation
A personal research dashboard for stock technicals, option-chain analysis, cash-secured put collateral sizing, theoretical Greeks, a Google Sheets trade journal, a simple roll cash-flow calculator, and an exploratory stock signal study.
Important limitations
This is a research prototype, not an order-entry or investment-advice system.
Yahoo Finance data may be delayed, incomplete, or unavailable. Confirm all prices, IV, volume, open interest, expirations, earnings, and dividends with your broker before trading.
Black–Scholes Greeks are theoretical estimates and do not model American early exercise or discrete dividends.
The stock signal study is not an options backtest and does not establish that any strategy is profitable.
The roll simulator calculates incremental cash flow only; it does not erase prior losses or calculate full trade economics.
Tax consequences, assignment, liquidity shocks, slippage, and commissions are not fully modeled.
Features
Cached Yahoo Finance historical data and option chains.
Standardized RSI implementation used throughout the app.
Price, rolling support/resistance, and realized-volatility context.
Option-chain bid/ask midpoint and spread visibility.
Theoretical delta, theta, vega, and gamma with explicit units.
Cash-secured put collateral budgeting and expiration breakeven.
Signed portfolio Greeks for long and short positions.
Google Sheets journal with named columns and input validation.
Roll cash-flow calculator.
Non-overlapping stock pullback signal study, explicitly separate from options backtesting.
Unit tests for core calculations.
Local setup
Requires Python 3.10+.
```bash
python -m venv .venv
# Windows:
.venv\\Scripts\\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```
The app can run without Google Sheets credentials; the journal feature requires them.
Google Sheets setup
Create a Google Cloud service account and enable the Google Sheets API and Google Drive API.
Share your target Google Sheet with the service account's email address.
Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`.
Fill in the service-account fields locally.
Ensure the sheet's first row uses these headers, in any order:
`Trade ID, Opened Date, Ticker, Strategy, Option Type, Side, Strike, Expiration, Contracts, Premium Per Share, Total Premium, Underlying At Entry, IV, Status, Notes`
The app will create the header row if the worksheet is empty. Existing sheets with a different schema are not modified automatically; create a new worksheet or align its headers first.
Never commit `.streamlit/secrets.toml` or service-account keys to GitHub. The `.gitignore` excludes the real secrets file.
For Streamlit Community Cloud, add the credentials using the app's Secrets settings, using TOML format.
Run tests
```bash
pytest -q
```
GitHub upload
Create a new repository, then upload these files or run:
```bash
git init
git add .
git commit -m "Initial PowerX options workstation"
git branch -M main
git remote add origin https://github.com/YOUR\_USERNAME/YOUR\_REPOSITORY.git
git push -u origin main
```
Before using for trading
Validate Greek values against a broker or trusted options calculator for known cases.
Confirm option quote freshness and market-hours behavior.
Check journal schema and reconcile positions against brokerage statements.
Add automated tests for more edge cases and your intended trading rules.
Do not use the prototype's outputs as a substitute for independent review.
