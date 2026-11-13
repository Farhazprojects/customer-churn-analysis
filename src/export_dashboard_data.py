"""Export the cleaned customer table with risk scores for the dashboards.

Run:  python src/export_dashboard_data.py
Output: dashboard/data/customers_scored.csv
"""
from pathlib import Path

import pandas as pd

from churn_analysis import CATEGORICAL, NUMERIC, fit_model, load_and_clean

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dashboard" / "data"
OUT.mkdir(parents=True, exist_ok=True)

df = load_and_clean()
scored, _, auc, model = fit_model(df)

df["tenure_band"] = pd.cut(df.tenure_months, [0, 6, 12, 24, 60], labels=[
    "0-6 months", "7-12 months", "13-24 months", "25+ months"])
df["tickets_band"] = pd.cut(df.support_tickets_90d, [-1, 0, 1, 2, 99], labels=[
    "0 tickets", "1 ticket", "2 tickets", "3+ tickets"])
df["churn_probability"] = model.predict_proba(
    df[CATEGORICAL + NUMERIC + ["logins_missing"]])[:, 1].round(4)
# The model was trained on 75% of customers. Scores for those customers are
# in-sample, so model performance pages should filter to the test set.
df["dataset"] = "Train"
df.loc[scored.index, "dataset"] = "Test"
# Deciles are ranked inside each set, so the test deciles match the analysis.
df["risk_decile"] = (df.groupby("dataset").churn_probability
                     .rank(method="first", ascending=False, pct=True)
                     .mul(10).apply(lambda x: int(-(-x // 1))))
df["annual_fee"] = (df.monthly_fee * 12).round(2)
df.to_csv(OUT / "customers_scored.csv", index=False)

lift = pd.read_csv(ROOT / "reports" / "tables" / "05_lift_by_decile.csv")
test = df[df.dataset == "Test"]
mine = test.groupby("risk_decile").churned.sum()
assert (mine.values == lift.churners.values).all(), (mine.values, lift.churners.values)
assert round(df.churned.mean(), 3) == 0.262
print(f"customers_scored  {len(df):,} rows, {df.shape[1]} columns, AUC {auc:.3f}. "
      f"Reconciliation PASS: test deciles match the lift table")
