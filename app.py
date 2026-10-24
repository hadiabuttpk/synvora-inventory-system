import io
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Synvora | Inventory Risk", page_icon="📦", layout="wide")

st.title("Synvora System")
st.subheader("Inventory Risk & Replenishment")
st.write("Monitor stock availability, identify replenishment risks, and generate reorder recommendations.")

REQUIRED_COLUMNS = [
    "Product ID", "Product Name", "Current Stock", "Avg Daily Sales",
    "Lead Time (Days)", "Safety Stock", "Open Orders"
]

SAMPLE_DATA = pd.DataFrame([
    {"Product ID": "P-1001", "Product Name": "Steel Bolts", "Current Stock": 120, "Avg Daily Sales": 18, "Lead Time (Days)": 5, "Safety Stock": 30, "Open Orders": 0},
    {"Product ID": "P-1002", "Product Name": "Packaging Boxes", "Current Stock": 420, "Avg Daily Sales": 35, "Lead Time (Days)": 4, "Safety Stock": 60, "Open Orders": 50},
    {"Product ID": "P-1003", "Product Name": "Safety Gloves", "Current Stock": 45, "Avg Daily Sales": 10, "Lead Time (Days)": 6, "Safety Stock": 25, "Open Orders": 0},
    {"Product ID": "P-1004", "Product Name": "Machine Filters", "Current Stock": 260, "Avg Daily Sales": 8, "Lead Time (Days)": 10, "Safety Stock": 35, "Open Orders": 20},
    {"Product ID": "P-1005", "Product Name": "Labels", "Current Stock": 75, "Avg Daily Sales": 6, "Lead Time (Days)": 7, "Safety Stock": 15, "Open Orders": 0},
])

with st.sidebar:
    st.header("Inventory data")
    uploaded_file = st.file_uploader("Upload inventory CSV", type=["csv"])
    use_sample = st.checkbox("Load example dataset", value=uploaded_file is None)
    st.divider()
    st.header("Planning settings")
    review_period = st.number_input("Extra days of stock to target", min_value=0, max_value=90, value=7, step=1,
                                    help="Additional stock to cover the time until the next inventory review.")

if uploaded_file is not None and not use_sample:
    try:
        raw_df = pd.read_csv(uploaded_file)
    except Exception as exc:
        st.error(f"Couldn't read this CSV file: {exc}")
        st.stop()
elif use_sample:
    raw_df = SAMPLE_DATA.copy()
else:
    st.info("Upload an inventory CSV or select ‘Load example dataset’ to begin.")
    st.stop()

missing = [col for col in REQUIRED_COLUMNS if col not in raw_df.columns]
if missing:
    st.error("Your file is missing these required columns: " + ", ".join(missing))
    st.markdown("**Required column names**")
    st.code(", ".join(REQUIRED_COLUMNS))
    st.download_button("Download sample CSV template", SAMPLE_DATA.to_csv(index=False).encode("utf-8"), "synvora_inventory_template.csv", "text/csv")
    st.stop()

# Keep only expected columns and validate numeric fields.
df = raw_df[REQUIRED_COLUMNS].copy()
NUMERIC_COLUMNS = ["Current Stock", "Avg Daily Sales", "Lead Time (Days)", "Safety Stock", "Open Orders"]
for col in NUMERIC_COLUMNS:
    df[col] = pd.to_numeric(df[col], errors="coerce")

invalid_rows = df[df[NUMERIC_COLUMNS].isna().any(axis=1)]
if not invalid_rows.empty:
    st.error(f"{len(invalid_rows)} row(s) have missing or non-numeric values in numeric columns. Fix them and upload again.")
    st.dataframe(invalid_rows, use_container_width=True)
    st.stop()

if (df[NUMERIC_COLUMNS] < 0).any().any():
    st.error("Stock, sales, lead time, safety stock and open orders must not be negative.")
    st.stop()
if (df["Lead Time (Days)"] < 0).any():
    st.error("Lead Time (Days) cannot be negative.")
    st.stop()
if df["Product ID"].astype(str).duplicated().any():
    st.warning("Duplicate Product ID(s) found. Check the data to avoid double-counting products.")

# Transparent rule-based calculations. Open orders reduce the suggested purchase quantity,
# but are not counted as available stock for immediate stock-out risk because due dates are unknown.
df["Days of Stock Left"] = df.apply(
    lambda r: round(r["Current Stock"] / r["Avg Daily Sales"], 1) if r["Avg Daily Sales"] > 0 else float("inf"), axis=1
)
df["Demand During Lead Time"] = df["Avg Daily Sales"] * df["Lead Time (Days)"]
df["Reorder Target"] = df["Avg Daily Sales"] * (df["Lead Time (Days)"] + review_period) + df["Safety Stock"]
df["Suggested Reorder Qty"] = (df["Reorder Target"] - df["Current Stock"] - df["Open Orders"]).clip(lower=0).apply(lambda x: int(round(x)))

def risk_level(row):
    if row["Avg Daily Sales"] == 0:
        return "No recent demand"
    if row["Current Stock"] <= row["Demand During Lead Time"]:
        return "Critical"
    if row["Current Stock"] <= row["Demand During Lead Time"] + row["Avg Daily Sales"] * 2:
        return "High"
    if row["Current Stock"] <= row["Reorder Target"]:
        return "Monitor"
    return "Healthy"

df["Risk Level"] = df.apply(risk_level, axis=1)
df["Recommendation"] = df.apply(
    lambda r: "Review urgently" if r["Risk Level"] == "Critical" else
    "Prioritize replenishment" if r["Risk Level"] == "High" else
    "Plan replenishment" if r["Risk Level"] == "Monitor" else
    "No immediate reorder suggested" if r["Risk Level"] == "Healthy" else
    "Check demand assumptions", axis=1
)

critical_count = int((df["Risk Level"] == "Critical").sum())
high_count = int((df["Risk Level"] == "High").sum())
reorder_count = int((df["Suggested Reorder Qty"] > 0).sum())

c1, c2, c3, c4 = st.columns(4)
c1.metric("Products analysed", len(df))
c2.metric("Critical risks", critical_count)
c3.metric("High risks", high_count)
c4.metric("Products needing reorder", reorder_count)

st.divider()
st.subheader("Automated risk alerts")
alerts = df[df["Risk Level"].isin(["Critical", "High", "Monitor"])].sort_values(
    by=["Risk Level", "Days of Stock Left"], ascending=[True, True]
)
if alerts.empty:
    st.success("No stock risks were identified using the current rules and data.")
else:
    for _, row in alerts.iterrows():
        days = "not available (zero average sales)" if row["Avg Daily Sales"] == 0 else f"{row['Days of Stock Left']:.1f} days"
        if row["Risk Level"] == "Critical":
            st.error(f"**{row['Product Name']} — CRITICAL:** {days} of stock left; supplier lead time is {row['Lead Time (Days)']:.0f} days. Review immediately.")
        elif row["Risk Level"] == "High":
            st.warning(f"**{row['Product Name']} — HIGH:** {days} of stock left. Prioritize replenishment review.")
        else:
            st.info(f"**{row['Product Name']} — MONITOR:** {days} of stock left. Plan a replenishment review.")

st.divider()
st.subheader("Inventory analysis")
show_cols = ["Product ID", "Product Name", "Current Stock", "Avg Daily Sales", "Days of Stock Left",
             "Lead Time (Days)", "Demand During Lead Time", "Safety Stock", "Open Orders",
             "Risk Level", "Suggested Reorder Qty", "Recommendation"]
display_df = df[show_cols].copy()
display_df["Days of Stock Left"] = display_df["Days of Stock Left"].replace(float("inf"), "No recent demand")
st.dataframe(display_df, use_container_width=True, hide_index=True)

chart_df = df[["Product Name", "Current Stock", "Reorder Target"]].set_index("Product Name")
st.subheader("Current stock vs. reorder target")
st.bar_chart(chart_df, use_container_width=True)

csv_bytes = display_df.to_csv(index=False).encode("utf-8")
st.download_button("Download analysed inventory report (CSV)", data=csv_bytes,
                   file_name="synvora_inventory_analysis.csv", mime="text/csv")

