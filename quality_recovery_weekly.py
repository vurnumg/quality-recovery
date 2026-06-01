# ============================================================
# quality_recovery_weekly.py
#
# Weekly Quality Recovery Strategy Automation
# - Runs every Saturday via GitHub Actions
# - Maintains portfolio_quality_recovery.csv
# - Sends one weekly HTML email
# - Flags BUY / SELL / HOLD / NO ACTION
# ============================================================

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

import pandas as pd
import yfinance as yf

# ============================================================
# SETTINGS
# ============================================================

PORTFOLIO_VALUE_GBP = 2000
MAX_POSITIONS = 5
POSITION_SIZE_GBP = PORTFOLIO_VALUE_GBP / MAX_POSITIONS

MIN_PULLBACK = -20
MAX_PULLBACK = -12

PROFIT_TARGET = 0.11
MAX_HOLD_DAYS = 365
MAX_HOLD_CALENDAR_DAYS = 511

PORTFOLIO_FILE = "portfolio_quality_recovery.csv"
HTML_FILE = "quality_recovery_weekly_email.html"

EXCLUDED_TICKERS = [
    "INTU",
    "MKTX",
    "ESTC",
    "PH",
    "WDAY",
]

UNIVERSE = {
    "V": "Visa", "MA": "Mastercard", "SPGI": "S&P Global", "MCO": "Moody's",
    "ICE": "Intercontinental Exchange", "CME": "CME Group", "FDS": "FactSet",
    "MSCI": "MSCI", "MKTX": "MarketAxess", "MORN": "Morningstar",

    "ROP": "Roper Technologies", "PH": "Parker-Hannifin", "ITW": "Illinois Tool Works",
    "TT": "Trane Technologies", "AME": "Ametek", "ROK": "Rockwell Automation",
    "EMR": "Emerson Electric", "NDSN": "Nordson", "CPRT": "Copart",
    "ODFL": "Old Dominion Freight Line",

    "DHR": "Danaher", "TMO": "Thermo Fisher Scientific", "ABT": "Abbott Laboratories",
    "SYK": "Stryker", "BSX": "Boston Scientific", "BDX": "Becton Dickinson",
    "WST": "West Pharmaceutical Services", "RMD": "ResMed", "MCK": "McKesson",
    "IQV": "IQVIA",

    "COST": "Costco", "TJX": "TJX Companies", "ORLY": "O'Reilly Automotive",
    "AZO": "AutoZone", "ROST": "Ross Stores", "MCD": "McDonald's",
    "CMG": "Chipotle Mexican Grill", "LULU": "Lululemon Athletica",
    "PG": "Procter & Gamble", "MNST": "Monster Beverage",

    "INTU": "Intuit", "ADBE": "Adobe", "ADSK": "Autodesk", "SNPS": "Synopsys",
    "FICO": "Fair Isaac", "WDAY": "Workday", "HUBS": "HubSpot",
    "MANH": "Manhattan Associates", "TYL": "Tyler Technologies", "ESTC": "Elastic",
}

SECTOR_MAP = {
    **{t: "Financial Infrastructure" for t in ["V", "MA", "SPGI", "MCO", "ICE", "CME", "FDS", "MSCI", "MKTX", "MORN"]},
    **{t: "Industrials" for t in ["ROP", "PH", "ITW", "TT", "AME", "ROK", "EMR", "NDSN", "CPRT", "ODFL"]},
    **{t: "Healthcare" for t in ["DHR", "TMO", "ABT", "SYK", "BSX", "BDX", "WST", "RMD", "MCK", "IQV"]},
    **{t: "Consumer" for t in ["COST", "TJX", "ORLY", "AZO", "ROST", "MCD", "CMG", "LULU", "PG", "MNST"]},
    **{t: "Software & Data" for t in ["INTU", "ADBE", "ADSK", "SNPS", "FICO", "WDAY", "HUBS", "MANH", "TYL", "ESTC"]},
}

TICKERS = [ticker for ticker in UNIVERSE.keys() if ticker not in EXCLUDED_TICKERS]

# ============================================================
# PORTFOLIO CSV
# ============================================================

def load_portfolio():
    required_columns = [
        "Ticker",
        "Company",
        "Sector",
        "EntryDate",
        "EntryPrice",
        "PositionSizeGBP",
    ]

    if not os.path.exists(PORTFOLIO_FILE):
        return pd.DataFrame(columns=required_columns)

    df = pd.read_csv(PORTFOLIO_FILE)

    for col in required_columns:
        if col not in df.columns:
            df[col] = ""

    df["Ticker"] = df["Ticker"].astype(str).str.upper().str.strip()
    df["Company"] = df["Company"].astype(str).str.strip()
    df["Sector"] = df["Sector"].astype(str).str.strip()
    df["EntryDate"] = df["EntryDate"].astype(str).str.strip()
    df["EntryPrice"] = pd.to_numeric(df["EntryPrice"], errors="coerce")
    df["PositionSizeGBP"] = pd.to_numeric(df["PositionSizeGBP"], errors="coerce")

    return df[required_columns].dropna(subset=["Ticker", "EntryPrice"])


def save_portfolio(df):
    df[[
        "Ticker",
        "Company",
        "Sector",
        "EntryDate",
        "EntryPrice",
        "PositionSizeGBP",
    ]].to_csv(PORTFOLIO_FILE, index=False)

# ============================================================
# DATA
# ============================================================

def download_data(tickers):
    print(f"Downloading {len(tickers)} tickers...")

    return yf.download(
        tickers=tickers,
        period="2y",
        interval="1d",
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )


def get_close(data, ticker):
    try:
        if isinstance(data.columns, pd.MultiIndex):
            close = data[ticker]["Close"].dropna()
        else:
            close = data["Close"].dropna()
        return close
    except Exception:
        return pd.Series(dtype=float)

# ============================================================
# SCANNER
# ============================================================

def scan_universe(data):
    rows = []

    for ticker in TICKERS:
        close = get_close(data, ticker)

        if len(close) < 253:
            continue

        current_price = close.iloc[-1]
        ma50 = close.rolling(50).mean().iloc[-1]
        ma200 = close.rolling(200).mean().iloc[-1]
        high_52w = close.tail(252).max()

        pullback = (current_price / high_52w - 1) * 100
        distance_above_200 = (current_price / ma200 - 1) * 100
        ma50_above_200 = (ma50 / ma200 - 1) * 100

        trend_ok = current_price > ma200 and ma50 > ma200
        pullback_ok = MIN_PULLBACK <= pullback <= MAX_PULLBACK
        qualifies = trend_ok and pullback_ok

        rows.append({
            "Ticker": ticker,
            "Company": UNIVERSE[ticker],
            "Sector": SECTOR_MAP[ticker],
            "Price": current_price,
            "50DMA": ma50,
            "200DMA": ma200,
            "52w High": high_52w,
            "Pullback %": pullback,
            "Distance Above 200DMA %": distance_above_200,
            "50DMA Above 200DMA %": ma50_above_200,
            "Trend OK": trend_ok,
            "Pullback OK": pullback_ok,
            "Qualifies": qualifies,
        })

    results = pd.DataFrame(rows)

    if results.empty:
        return results, results

    qualified = results[results["Qualifies"]].copy()

    if not qualified.empty:
        qualified["Pullback Rank"] = qualified["Pullback %"].rank(
            ascending=True,
            method="min",
        )

        qualified["Trend Strength Rank"] = qualified[
            "Distance Above 200DMA %"
        ].rank(
            ascending=False,
            method="min",
        )

        qualified["Combined Rank Score"] = (
            qualified["Pullback Rank"] + qualified["Trend Strength Rank"]
        )

        qualified = qualified.sort_values(
            ["Combined Rank Score", "Pullback %"],
            ascending=[True, True],
        ).reset_index(drop=True)

        qualified["Rank"] = qualified.index + 1

    return results, qualified

# ============================================================
# POSITION REVIEW
# ============================================================

def review_positions(portfolio, data, run_date):
    rows = []
    sells = []
    holds = []

    for _, row in portfolio.iterrows():
        ticker = row["Ticker"]
        close = get_close(data, ticker)

        if close.empty:
            continue

        current_price = close.iloc[-1]
        entry_price = row["EntryPrice"]
        entry_date = pd.to_datetime(row["EntryDate"])

        return_pct = current_price / entry_price - 1

        # IMPORTANT:
        # The backtest used trading bars, not calendar days.
        # This counts actual available trading days from EntryDate onward.
        trading_days_held = close.loc[close.index >= entry_date].shape[0]

        # Also keep calendar days for information only.
        calendar_days_held = (pd.to_datetime(run_date) - entry_date).days

        if return_pct >= PROFIT_TARGET:
            action = "SELL - PROFIT TARGET"
            sells.append(ticker)
        elif trading_days_held >= MAX_HOLD_DAYS or calendar_days_held >= MAX_HOLD_CALENDAR_DAYS:
            action = "SELL - TIME EXIT"
            sells.append(ticker)
        else:
            action = "HOLD"
            holds.append(ticker)

        rows.append({
            "Ticker": ticker,
            "Company": row["Company"],
            "Sector": row["Sector"],
            "EntryDate": row["EntryDate"],
            "EntryPrice": entry_price,
            "CurrentPrice": current_price,
            "ReturnPct": return_pct,
            "TradingDaysHeld": trading_days_held,
            "CalendarDaysHeld": calendar_days_held,
            "Action": action,
        })

    return pd.DataFrame(rows), sells, holds

# ============================================================
# PORTFOLIO UPDATE
# ============================================================

def build_new_portfolio(current_portfolio, position_review, buy_candidates, run_date):
    sell_tickers = set(
        position_review.loc[
            position_review["Action"].str.startswith("SELL"),
            "Ticker",
        ].tolist()
    ) if not position_review.empty else set()

    retained = current_portfolio[~current_portfolio["Ticker"].isin(sell_tickers)].copy()

    already_held = set(retained["Ticker"].tolist())
    available_slots = MAX_POSITIONS - len(retained)

    buys = []

    if available_slots > 0 and not buy_candidates.empty:
        eligible_buys = buy_candidates[
            ~buy_candidates["Ticker"].isin(already_held)
        ].head(available_slots)

        for _, row in eligible_buys.iterrows():
            buys.append(row["Ticker"])

            retained = pd.concat([
                retained,
                pd.DataFrame([{
                    "Ticker": row["Ticker"],
                    "Company": row["Company"],
                    "Sector": row["Sector"],
                    "EntryDate": run_date,
                    "EntryPrice": row["Price"],
                    "PositionSizeGBP": POSITION_SIZE_GBP,
                }])
            ], ignore_index=True)

    return retained, buys, sorted(list(sell_tickers))

# ============================================================
# HTML EMAIL
# ============================================================

def fmt_pct(x):
    try:
        return f"{x:.2%}"
    except Exception:
        return ""


def fmt_num(x):
    try:
        return f"{x:.2f}"
    except Exception:
        return ""


def build_html_email(run_date, portfolio_before, position_review, qualified, buy_candidates, buys, sells, holds):
    if sells or buys:
        header_colour = "#0b6b3a"
        headline = "QUALITY RECOVERY ACTIONS REQUIRED"
    else:
        header_colour = "#444444"
        headline = "QUALITY RECOVERY: NO ACTION REQUIRED"

    sell_rows = ""
    for ticker in sells:
        row = position_review[position_review["Ticker"] == ticker]
        if not row.empty:
            r = row.iloc[0]
            sell_rows += f"""
            <tr>
                <td style='color:#b00020;'><strong>{r['Action']}</strong></td>
                <td><strong>{ticker}</strong></td>
                <td>{r['Company']}</td>
                <td>{fmt_num(r['EntryPrice'])}</td>
                <td>{fmt_num(r['CurrentPrice'])}</td>
                <td>{fmt_pct(r['ReturnPct'])}</td>
                <td>{int(r['TradingDaysHeld'])}</td>
            </tr>
            """

    buy_rows = ""
    for ticker in buys:
        row = buy_candidates[buy_candidates["Ticker"] == ticker]
        if not row.empty:
            r = row.iloc[0]
            buy_rows += f"""
            <tr>
                <td style='color:#0b6b3a;'><strong>BUY</strong></td>
                <td><strong>{ticker}</strong></td>
                <td>{r['Company']}</td>
                <td>{r['Sector']}</td>
                <td>{fmt_num(r['Price'])}</td>
                <td>{r['Pullback %']:.2f}%</td>
                <td>£{POSITION_SIZE_GBP:,.0f}</td>
            </tr>
            """

    hold_rows = ""
    if not position_review.empty:
        for _, r in position_review[position_review["Action"] == "HOLD"].iterrows():
            hold_rows += f"""
            <tr>
                <td><strong>HOLD</strong></td>
                <td><strong>{r['Ticker']}</strong></td>
                <td>{r['Company']}</td>
                <td>{fmt_num(r['EntryPrice'])}</td>
                <td>{fmt_num(r['CurrentPrice'])}</td>
                <td>{fmt_pct(r['ReturnPct'])}</td>
                <td>{int(r['TradingDaysHeld'])}</td>
            </tr>
            """

    if not sell_rows:
        sell_rows = "<tr><td colspan='7'>No sells.</td></tr>"

    if not buy_rows:
        buy_rows = "<tr><td colspan='7'>No buys.</td></tr>"

    if not hold_rows:
        hold_rows = "<tr><td colspan='7'>No current holds.</td></tr>"

    qualifying_rows = ""
    if qualified is not None and not qualified.empty:
        for _, r in qualified.iterrows():
            qualifying_rows += f"""
            <tr>
                <td>{int(r['Rank'])}</td>
                <td><strong>{r['Ticker']}</strong></td>
                <td>{r['Company']}</td>
                <td>{r['Sector']}</td>
                <td>{fmt_num(r['Price'])}</td>
                <td>{r['Pullback %']:.2f}%</td>
                <td>{r['Distance Above 200DMA %']:.2f}%</td>
                <td>{r['50DMA Above 200DMA %']:.2f}%</td>
            </tr>
            """
    else:
        qualifying_rows = "<tr><td colspan='8'>No qualifying stocks this week.</td></tr>"

    return f"""
    <html>
    <head>
        <style>
            body {{
                font-family: Arial, sans-serif;
                color: #222222;
                line-height: 1.5;
                background: #ffffff;
            }}
            .container {{
                max-width: 1050px;
                margin: auto;
                padding: 20px;
            }}
            .header {{
                background: {header_colour};
                color: #ffffff;
                padding: 20px;
                border-radius: 8px;
            }}
            .box {{
                background: #f5f5f5;
                padding: 16px;
                border-radius: 8px;
                margin: 20px 0;
            }}
            table {{
                border-collapse: collapse;
                width: 100%;
                margin-top: 15px;
            }}
            th, td {{
                border: 1px solid #dddddd;
                padding: 8px;
                text-align: left;
                font-size: 14px;
            }}
            th {{
                background: #eeeeee;
            }}
            .footer {{
                margin-top: 25px;
                font-size: 13px;
                color: #666666;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Weekly Quality Recovery Review</h1>
                <h2>{headline}</h2>
            </div>

            <div class="box">
                <p><strong>Run date:</strong> {run_date}</p>
                <p><strong>Strategy:</strong> Quality Recovery</p>
                <p><strong>Pullback range:</strong> 12% to 20% below 52-week high</p>
                <p><strong>Trend filter:</strong> Price above 200DMA and 50DMA above 200DMA</p>
                <p><strong>Profit target:</strong> {PROFIT_TARGET:.0%}</p>
                <p><strong>Max hold:</strong> {MAX_HOLD_DAYS} trading days</p>
                <p><strong>Time-exit logic:</strong> Counts actual trading days from EntryDate, not calendar days.</p>
                <p><strong>Portfolio:</strong> £{PORTFOLIO_VALUE_GBP:,.0f}, max {MAX_POSITIONS} positions, £{POSITION_SIZE_GBP:,.0f} each</p>
                <p><strong>Current positions before update:</strong> {len(portfolio_before)}</p>
                <p><strong>Qualifying stocks this week:</strong> {0 if qualified is None else len(qualified)}</p>
            </div>

            <h2>Sells</h2>
            <table>
                <tr>
                    <th>Action</th><th>Ticker</th><th>Company</th><th>Entry</th><th>Current</th><th>Return</th><th>Trading Days</th>
                </tr>
                {sell_rows}
            </table>

            <h2>Buys</h2>
            <table>
                <tr>
                    <th>Action</th><th>Ticker</th><th>Company</th><th>Sector</th><th>Price</th><th>Pullback</th><th>Suggested Size</th>
                </tr>
                {buy_rows}
            </table>

            <h2>Holds</h2>
            <table>
                <tr>
                    <th>Action</th><th>Ticker</th><th>Company</th><th>Entry</th><th>Current</th><th>Return</th><th>Trading Days</th>
                </tr>
                {hold_rows}
            </table>

            <h2>All Qualifying Candidates</h2>
            <table>
                <tr>
                    <th>Rank</th><th>Ticker</th><th>Company</th><th>Sector</th><th>Price</th><th>Pullback</th><th>Above 200DMA</th><th>50DMA Above 200DMA</th>
                </tr>
                {qualifying_rows}
            </table>

            <div class="footer">
                <p>portfolio_quality_recovery.csv has been updated automatically. Manually place only the trades shown above.</p>
            </div>
        </div>
    </body>
    </html>
    """

# ============================================================
# EMAIL
# ============================================================

def send_email(subject, html_body):
    smtp_server = os.environ.get("SMTP_SERVER")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_username = os.environ.get("SMTP_USERNAME")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    email_from = os.environ.get("EMAIL_FROM")
    email_to = os.environ.get("EMAIL_TO")

    if not all([smtp_server, smtp_username, smtp_password, email_from, email_to]):
        print("Email secrets not fully configured. HTML file created but email not sent.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to

    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(smtp_username, smtp_password)
        server.sendmail(email_from, email_to.split(","), msg.as_string())

    print("Email sent.")

# ============================================================
# MAIN
# ============================================================

def run_weekly_review():
    run_date = datetime.now().strftime("%Y-%m-%d")

    portfolio_before = load_portfolio()
    all_download_tickers = sorted(list(set(TICKERS + portfolio_before["Ticker"].tolist())))

    data = download_data(all_download_tickers)

    full_universe, qualified = scan_universe(data)
    position_review, sells, holds = review_positions(portfolio_before, data, run_date)

    available_slots_before_buys = MAX_POSITIONS - (len(portfolio_before) - len(sells))

    buy_candidates = pd.DataFrame()
    if qualified is not None and not qualified.empty and available_slots_before_buys > 0:
        held_after_sells = set(portfolio_before[~portfolio_before["Ticker"].isin(sells)]["Ticker"].tolist())
        buy_candidates = qualified[~qualified["Ticker"].isin(held_after_sells)].head(available_slots_before_buys).copy()

    new_portfolio, buys, sells = build_new_portfolio(
        current_portfolio=portfolio_before,
        position_review=position_review,
        buy_candidates=buy_candidates,
        run_date=run_date,
    )

    html_body = build_html_email(
        run_date=run_date,
        portfolio_before=portfolio_before,
        position_review=position_review,
        qualified=qualified,
        buy_candidates=buy_candidates,
        buys=buys,
        sells=sells,
        holds=holds,
    )

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html_body)

    save_portfolio(new_portfolio)

    full_universe.to_csv("quality_recovery_full_universe_scan.csv", index=False)
    qualified.to_csv("quality_recovery_qualified_candidates.csv", index=False)
    position_review.to_csv("quality_recovery_position_review.csv", index=False)
    new_portfolio.to_csv("portfolio_quality_recovery.csv", index=False)

    subject = "Weekly Quality Recovery Review"

    if sells or buys:
        subject += " - ACTION REQUIRED"
    else:
        subject += " - No Action"

    send_email(subject, html_body)

    print("==============================")
    print("WEEKLY QUALITY RECOVERY REVIEW")
    print("==============================")
    print(f"Run date: {run_date}")
    print(f"Current positions before update: {len(portfolio_before)}")
    print(f"Qualifying stocks: {0 if qualified is None else len(qualified)}")
    print(f"SELL: {', '.join(sells) if sells else 'None'}")
    print(f"BUY: {', '.join(buys) if buys else 'None'}")
    print(f"HOLD: {', '.join(holds) if holds else 'None'}")
    print(f"HTML email saved to: {HTML_FILE}")
    print(f"{PORTFOLIO_FILE} updated.")


if __name__ == "__main__":
    run_weekly_review()
