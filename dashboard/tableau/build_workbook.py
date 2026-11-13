"""Build the Tableau packaged workbook for this project.

Run:  python dashboard/tableau/build_workbook.py
Needs: pip install tableauhyperapi
"""
import sys
from pathlib import Path
import pandas as pd
from twb_builder import DS, sheet, dashboard, build, declare_parameters

ROOT = Path(__file__).resolve().parents[2]
df = pd.read_csv(ROOT / "dashboard" / "data" / "customers_scored.csv")
df["tenure_order"] = df.tenure_band.map({"0-6 months": 1, "7-12 months": 2, "13-24 months": 3, "25+ months": 4})
df["tickets_order"] = df.tickets_band.map({"0 tickets": 1, "1 ticket": 2, "2 tickets": 3, "3+ tickets": 4})
DIMS = ("seats", "tenure_months", "support_tickets_90d", "logins_missing", "risk_decile", "tenure_order", "tickets_order")
RATE = "SUM([churned]) / COUNT([customer_id])"
overall = df.churned.mean()

def add_calcs(d):
    d.calc("c_rate", "Churn rate %", RATE, "pct")
    d.calc("c_customers", "Customers", "COUNT([customer_id])", "int")
    d.calc("c_fee_lost", "Monthly fee lost", "SUM(IF [churned] = 1 THEN [monthly_fee] END)", "usd")
    d.calc("c_lift", "Lift", f"({RATE}) / MIN({{FIXED : {RATE}}})", "dec2")
    return d

fm = {"churned": "int", "churn_probability": "pct"}
ds = add_calcs(DS("churn_customers", "All customers", df, dims=DIMS, formats=fm))
test = df[df.dataset == "Test"].copy()
dt = add_calcs(DS("churn_test", "Test customers", test, dims=DIMS, formats=fm))
test_rate = test.churned.mean()

# One row per customer per campaign depth: depth k holds every test customer in deciles 1..k.
depth = pd.concat([test.loc[test.risk_decile <= k, ["customer_id", "churned", "annual_fee"]].assign(deciles_contacted=k)
                   for k in range(1, 11)], ignore_index=True)
P = declare_parameters([("Parameter 1", "Save rate", "real", 0.25, 0.05, 0.5, 0.05, "pct"),
                        ("Parameter 2", "Offer cost per customer ($)", "integer", 60, 20, 120, 10, None)])
dd = DS("campaign_depth", "Campaign depth (test customers)", depth, dims=("deciles_contacted",))
SAVED = "[Parameters].[Parameter 1] * SUM(IF [churned] = 1 THEN [annual_fee] END)"
SPEND = "[Parameters].[Parameter 2] * COUNT([customer_id])"
dd.calc("c_net", "Net value", f"{SAVED} - {SPEND}", "usd")
dd.calc("c_roi", "Return on spend %", f"({SAVED} - {SPEND}) / ({SPEND})", "pct")
dd.calc("c_contacted", "Customers contacted", "COUNT([customer_id])", "int")
dd.calc("c_saved", "Revenue saved", SAVED, "usd")

S = []
S.append(sheet(ds, "Customer count", big="usr:c_customers:qk", title="Customers"))
S.append(sheet(ds, "Churned customers", big="sum:churned:qk"))
S.append(sheet(ds, "Churn rate", big="usr:c_rate:qk"))
S.append(sheet(ds, "Monthly fee lost", big="usr:c_fee_lost:qk", title="Monthly fee lost to churn"))
ref = ("usr:c_rate:qk", round(overall, 4), f"Overall {overall:.1%}")
def seg(name, dim, title, order=None):
    S.append(sheet(ds, name, cols=[f"none:{dim}:nk"], rows=["usr:c_rate:qk"], mark="Bar", label=True, title=title,
                   refline=ref, sort=(f"none:{dim}:nk", order, "ASC") if order else None))
seg("Churn by contract type", "contract_type", "Churn rate by contract type")
seg("Churn by payment method", "payment_method", "Churn rate by payment method")
seg("Churn by tenure", "tenure_band", "Churn rate by tenure", "min:tenure_order:qk")
seg("Churn by support tickets", "tickets_band", "Churn rate by support tickets in 90 days", "min:tickets_order:qk")
seg("Churn by onboarding", "completed_onboarding", "Churn rate by completed onboarding")
seg("Churn by price increase", "price_increase_last_12m", "Churn rate by price increase in last 12 months")
seg("Churn by plan", "plan", "Churn rate by plan")

S.append(sheet(dt, "Test customers", big="usr:c_customers:qk", title="Test customers (not used in training)"))
S.append(sheet(dt, "Test churners", big="sum:churned:qk", title="Churned in test set"))
S.append(sheet(dt, "Test churn rate", big="usr:c_rate:qk", title="Test churn rate"))
S.append(sheet(dt, "Churn by risk decile", cols=["none:risk_decile:ok"], rows=["usr:c_rate:qk"], mark="Bar", label=True,
               refline=("usr:c_rate:qk", round(test_rate, 4), f"Test set overall {test_rate:.1%}"),
               title="Actual churn rate by predicted risk decile (1 = highest risk)"))
S.append(sheet(dt, "Lift by risk decile", cols=["none:risk_decile:ok"], rows=["usr:c_lift:qk"], mark="Bar", label=True,
               refline=("usr:c_lift:qk", 1, "No better than random"), title="Lift by risk decile"))
S.append(sheet(dt, "Predicted probability by decile", cols=["none:risk_decile:ok"], rows=["avg:churn_probability:qk"],
               mark="Bar", label=True, title="Average predicted churn probability by risk decile", mark_color="#d9822b"))

S.append(sheet(dd, "Net value by campaign depth", cols=["none:deciles_contacted:ok"], rows=["usr:c_net:qk"], mark="Bar",
               label=True, title="Net value of the retention offer by number of risk deciles contacted"))
S.append(sheet(dd, "Return on spend by depth", cols=["none:deciles_contacted:ok"], rows=["usr:c_roi:qk"], mark="Bar",
               label=True, title="Return on spend by number of risk deciles contacted", mark_color="#d9822b"))
S.append(sheet(dd, "Customers contacted by depth", cols=["none:deciles_contacted:ok"], rows=["usr:c_contacted:qk"],
               mark="Bar", label=True, title="Customers contacted", mark_color="#9aa5b1"))
S.append(sheet(dd, "Revenue saved by depth", cols=["none:deciles_contacted:ok"], rows=["usr:c_saved:qk"],
               mark="Bar", label=True, title="Revenue saved (12 months of fees)", mark_color="#9aa5b1"))

note = "Synthetic data generated for a portfolio project."
D1 = dashboard("Who churns", "Customer churn: who leaves",
               [("Customer count", 0, 56, 325, 104), ("Churned customers", 325, 56, 325, 104), ("Churn rate", 650, 56, 325, 104),
                ("Monthly fee lost", 975, 56, 325, 104),
                ("Churn by contract type", 0, 160, 325, 330), ("Churn by tenure", 325, 160, 487, 330), ("Churn by support tickets", 812, 160, 488, 330),
                ("Churn by plan", 0, 490, 325, 330), ("Churn by payment method", 325, 490, 325, 330),
                ("Churn by onboarding", 650, 490, 325, 330), ("Churn by price increase", 975, 490, 325, 330)],
               subtitle=note + " Click a plan to filter the page.")
D2 = dashboard("Risk model", "Risk model performance on the test set",
               [("Test customers", 0, 56, 433, 104), ("Test churners", 433, 56, 433, 104), ("Test churn rate", 866, 56, 434, 104),
                ("Churn by risk decile", 0, 160, 1300, 330), ("Lift by risk decile", 0, 490, 650, 330),
                ("Predicted probability by decile", 650, 490, 650, 330)],
               subtitle=note + " Logistic regression, scored on the 25% of customers held out from training.")
D3 = dashboard("Retention offer", "Retention offer: what is it worth?",
               [("Net value by campaign depth", 0, 130, 1300, 360), ("Return on spend by depth", 0, 490, 434, 330),
                ("Customers contacted by depth", 434, 490, 433, 330), ("Revenue saved by depth", 867, 490, 433, 330)],
               params=[("Parameter 1", 0, 60, 400, 66), ("Parameter 2", 420, 60, 400, 66)],
               subtitle=note + " Move the sliders to change the assumptions. Test customers only.")
acts = [("Filter by plan", "Who churns", "Churn by plan")]
out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("customer_churn_dashboard.twbx")
build(out, [ds, dt, dd], S, [D1, D2, D3], params=P, acts=acts)
print(f"Wrote {out.name}")
