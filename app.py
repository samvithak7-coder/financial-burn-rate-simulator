import numpy as np
import pandas as pd
import streamlit as st
from operator import gt, lt, ge, le

st.set_page_config(page_title="Financial Analysis & Burn Rate Simulator", layout="wide")

st.title("💸 Financial Analysis & Burn Rate Simulator")
st.markdown("Upload your monthly financials (CSV or Excel) to get automatic analysis, scenarios and runway.")


# ---------------------------------------------------------------- helpers
def clean_number(series):
    text = series.astype(str)
    text = text.str.replace("(", "-", regex=False).str.replace(")", "", regex=False)
    text = text.str.replace("$", "", regex=False).str.replace(",", "", regex=False)
    text = text.str.replace("%", "", regex=False).str.strip()
    return pd.to_numeric(text, errors="coerce")


def guess_index(columns, keywords):
    for i, col in enumerate(columns):
        if any(k in str(col).lower() for k in keywords):
            return i
    return 0


def read_upload(file):
    name = file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(file)
    return pd.read_excel(file)


def simulate(last_rev, last_exp, rev_g, exp_g, cash, n):
    steps = np.arange(1, n + 1)
    rev = last_rev * (1 + rev_g) ** steps
    exp = last_exp * (1 + exp_g) ** steps
    net = rev - exp
    balance = cash + np.cumsum(net)
    return rev, exp, net, balance


def runway_months(balance):
    hits = np.flatnonzero(np.less_equal(balance, 0))
    if len(hits) == 0:
        return None
    return int(hits[0]) + 1


def sample_data():
    rng = np.random.default_rng(42)
    months = pd.date_range(start="2025-05-01", periods=18, freq="MS")
    revenue = rng.normal(50000, 4000, 18) + np.arange(18) * 1000
    expenses = rng.normal(65000, 2500, 18)
    return pd.DataFrame({"Month": months.strftime("%Y-%m"),
                         "Revenue": np.round(revenue, 2),
                         "Expenses": np.round(expenses, 2)})


# ---------------------------------------------------------------- sidebar
st.sidebar.header("1. Your data")
uploaded = st.sidebar.file_uploader("Upload CSV or Excel", type=["csv", "xlsx", "xls"])
st.sidebar.download_button("Download sample template", sample_data().to_csv(index=False),
                           file_name="financials_template.csv", mime="text/csv")

st.sidebar.header("2. Assumptions")
starting_cash = st.sidebar.number_input("Current cash balance ($)", min_value=0.0, value=500000.0, step=10000.0)
horizon = st.sidebar.slider("Forecast horizon (months)", 6, 60, 24)
override = st.sidebar.checkbox("Override growth rates manually")

# ---------------------------------------------------------------- load
if uploaded is not None:
    try:
        raw = read_upload(uploaded)
    except Exception as e:
        st.error("Could not read that file: " + str(e))
        st.stop()
else:
    raw = sample_data()
    st.info("No file uploaded yet, so you are seeing sample data. Upload a file in the sidebar to analyse your own numbers.")

if raw.shape[1] == 0 or len(raw) == 0:
    st.error("The file appears to be empty.")
    st.stop()

cols = list(raw.columns)
with st.expander("Column mapping (auto-detected, change if wrong)", expanded=False):
    m1, m2, m3 = st.columns(3)
    month_col = m1.selectbox("Month / date column", cols, index=guess_index(cols, ["month", "date", "period"]))
    rev_col = m2.selectbox("Revenue column", cols, index=guess_index(cols, ["revenue", "sales", "income"]))
    exp_col = m3.selectbox("Expenses column", cols, index=guess_index(cols, ["expense", "cost", "spend"]))

df = pd.DataFrame({
    "Month": pd.to_datetime(raw[month_col], errors="coerce"),
    "Revenue": clean_number(raw[rev_col]),
    "Expenses": clean_number(raw[exp_col]),
}).dropna().sort_values("Month").reset_index(drop=True)

if len(df) == 0:
    st.error("No usable rows found. Check the column mapping: dates must be parseable (like 2025-05 or 05/2025) and Revenue and Expenses must be numbers.")
    st.stop()
if len(df) == 1:
    st.error("Need at least 2 months of data to analyse trends.")
    st.stop()

df["Net_Cash_Flow"] = df["Revenue"] - df["Expenses"]

# ---------------------------------------------------------------- analysis
recent = df.tail(3)
base_rev = float(recent["Revenue"].mean())
base_exp = float(recent["Expenses"].mean())
avg_net = float(recent["Net_Cash_Flow"].mean())

rev_trend = float(np.clip(df["Revenue"].pct_change().tail(6).mean(), -0.2, 0.2))
exp_trend = float(np.clip(df["Expenses"].pct_change().tail(6).mean(), -0.2, 0.2))
rev_trend = 0.0 if np.isnan(rev_trend) else rev_trend
exp_trend = 0.0 if np.isnan(exp_trend) else exp_trend

if override:
    rev_g = st.sidebar.slider("Monthly revenue growth (%)", -10.0, 20.0, round(rev_trend * 100, 1), 0.5) / 100
    exp_g = st.sidebar.slider("Monthly expense growth (%)", -10.0, 20.0, round(exp_trend * 100, 1), 0.5) / 100
else:
    rev_g, exp_g = rev_trend, exp_trend

spread = 0.02
scenarios = {
    "Pessimistic": (rev_g - spread, exp_g + spread / 2),
    "Base": (rev_g, exp_g),
    "Optimistic": (rev_g + spread, exp_g - spread / 2),
}

future_months = pd.date_range(start=df["Month"].iloc[-1] + pd.DateOffset(months=1), periods=horizon, freq="MS")
balances = {}
results = {}
for name, (rg, eg) in scenarios.items():
    rev, exp, net, bal = simulate(base_rev, base_exp, rg, eg, starting_cash, horizon)
    balances[name] = bal
    results[name] = (rev, exp, net, bal, runway_months(bal))

base_rev_f, base_exp_f, base_net_f, base_bal_f, base_runway = results["Base"]

# ---------------------------------------------------------------- metrics
burn = -avg_net
c1, c2, c3, c4 = st.columns(4)
c1.metric("Avg Revenue (last 3 mo)", f"${base_rev:,.0f}")
c2.metric("Avg Expenses (last 3 mo)", f"${base_exp:,.0f}")
c3.metric("Net Monthly Burn" if gt(burn, 0) else "Net Monthly Surplus", f"${abs(burn):,.0f}")
if base_runway is not None:
    c4.metric("Base-case Runway", str(base_runway) + " months")
elif ge(base_net_f[-1], 0):
    c4.metric("Base-case Runway", "Sustainable")
else:
    c4.metric("Base-case Runway", "Over " + str(horizon) + " months")

st.markdown("---")

# ---------------------------------------------------------------- insights
st.subheader("🧠 Key insights")
insights = []

if gt(burn, 0):
    insights.append("🔴 You are burning about **${:,.0f}/month** (last 3 months average).".format(burn))
else:
    insights.append("🟢 You are cash-flow positive by about **${:,.0f}/month** (last 3 months average).".format(abs(burn)))

insights.append("📈 Revenue trend: **{:+.1%} per month** (last 6 months). Expense trend: **{:+.1%} per month**.".format(rev_trend, exp_trend))

if gt(exp_trend, rev_trend):
    insights.append("⚠️ Expenses are growing faster than revenue, which will widen the gap over time.")
elif gt(rev_trend, exp_trend):
    insights.append("✅ Revenue is growing faster than expenses, so the gap is narrowing.")

ratio = base_exp / base_rev if gt(base_rev, 0) else float("nan")
if not np.isnan(ratio):
    insights.append("💼 Expenses are **{:.0%}** of revenue.".format(ratio))

best = df.loc[df["Net_Cash_Flow"].idxmax()]
worst = df.loc[df["Net_Cash_Flow"].idxmin()]
insights.append("🏆 Best month: **{}** (net ${:,.0f}). Weakest month: **{}** (net ${:,.0f}).".format(
    best["Month"].strftime("%Y-%m"), best["Net_Cash_Flow"], worst["Month"].strftime("%Y-%m"), worst["Net_Cash_Flow"]))

if base_runway is not None:
    out_date = future_months[base_runway - 1].strftime("%b %Y")
    insights.append("⏳ At current trends, cash runs out in about **{} months ({})**.".format(base_runway, out_date))
    if lt(base_runway, 6):
        insights.append("🚨 Runway is under 6 months. Consider cutting costs or raising funds soon.")
    elif lt(base_runway, 12):
        insights.append("🟠 Runway is under 12 months. Start planning your next funding or cost actions.")
elif gt(burn, 0):
    insights.append("⏳ Cash lasts beyond your {}-month forecast horizon under the base case.".format(horizon))

if gt(burn, 0) and gt(rev_g, exp_g) and gt(base_rev, 0):
    months_to_breakeven = int(np.ceil(np.log(base_exp / base_rev) / np.log((1 + rev_g) / (1 + exp_g))))
    if le(months_to_breakeven, 120):
        insights.append("🎯 Estimated break-even in about **{} months** if trends hold.".format(max(months_to_breakeven, 1)))

for line in insights:
    st.markdown("- " + line.replace("$", "\\$"))

st.markdown("---")

# ---------------------------------------------------------------- charts
left, right = st.columns(2)
with left:
    st.subheader("📊 Historical performance")
    st.line_chart(df.set_index("Month")[["Revenue", "Expenses", "Net_Cash_Flow"]])
with right:
    st.subheader("🔮 Cash balance scenarios")
    scen_df = pd.DataFrame(balances, index=future_months)[["Pessimistic", "Base", "Optimistic"]]
    st.line_chart(scen_df)

st.subheader("Scenario summary")
rows = []
for name in ["Pessimistic", "Base", "Optimistic"]:
    rg, eg = scenarios[name]
    rw = results[name][4]
    rows.append({
        "Scenario": name,
        "Revenue growth / mo": "{:+.1%}".format(rg),
        "Expense growth / mo": "{:+.1%}".format(eg),
        "Runway": (str(rw) + " months") if rw is not None else "Beyond horizon",
        "Ending cash": "${:,.0f}".format(results[name][3][-1]),
    })
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ---------------------------------------------------------------- data
with st.expander("📋 Cleaned historical data"):
    show = df.copy()
    show["Month"] = show["Month"].dt.strftime("%Y-%m")
    st.dataframe(show, use_container_width=True, hide_index=True)

forecast_df = pd.DataFrame({
    "Month": future_months.strftime("%Y-%m"),
    "Revenue": np.round(base_rev_f, 2),
    "Expenses": np.round(base_exp_f, 2),
    "Net_Cash_Flow": np.round(base_net_f, 2),
    "Cash_Balance": np.round(base_bal_f, 2),
})
with st.expander("📋 Base-case forecast"):
    st.dataframe(forecast_df, use_container_width=True, hide_index=True)
st.download_button("⬇️ Download base-case forecast (CSV)", forecast_df.to_csv(index=False),
                   file_name="forecast.csv", mime="text/csv")