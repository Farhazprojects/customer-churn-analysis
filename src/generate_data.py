"""Generate the synthetic subscription dataset used in this project.

The data is made up. The company is a fictional business that sells
bookkeeping software to small firms on a monthly subscription. I generate
the customers with a fixed seed so the CSV can be rebuilt exactly.

Churn is drawn from a logistic model whose drivers are written below.
I also added a little mess (missing values, one column that carries no
signal) so the cleaning and testing steps have real work to do.

Run:  python src/generate_data.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 7
N = 7000
OUT = Path(__file__).resolve().parents[1] / "data" / "subscriptions.csv"
rng = np.random.default_rng(SEED)

plan = rng.choice(["Basic", "Standard", "Premium"], N, p=[0.45, 0.38, 0.17])
contract = rng.choice(["Monthly", "Annual"], N, p=[0.62, 0.38])
payment = rng.choice(["Card auto-pay", "Direct debit", "Manual invoice"],
                     N, p=[0.48, 0.30, 0.22])
industry = rng.choice(["Trades", "Retail", "Hospitality", "Professional services",
                       "Health"], N, p=[0.26, 0.22, 0.18, 0.22, 0.12])
state = rng.choice(["NSW", "VIC", "QLD", "WA", "SA", "Other"], N,
                   p=[0.32, 0.26, 0.20, 0.10, 0.07, 0.05])

tenure = np.clip(rng.gamma(1.6, 11, N).round(), 1, 60).astype(int)
seats = np.where(plan == "Basic", rng.integers(1, 4, N),
                 np.where(plan == "Standard", rng.integers(2, 9, N),
                          rng.integers(5, 26, N)))
base_fee = pd.Series(plan).map({"Basic": 29, "Standard": 59, "Premium": 119}).to_numpy()
monthly_fee = (base_fee + 6 * (seats - 1) * (plan != "Basic")
               ) * np.where(contract == "Annual", 0.85, 1.0)
monthly_fee = monthly_fee.round(2)

# Product usage in the last 30 days. Premium customers log in more.
logins = rng.poisson(np.where(plan == "Premium", 16, np.where(plan == "Standard", 11, 7)))
tickets = rng.poisson(0.9, N)                     # support tickets, last 90 days
onboarded = rng.random(N) < np.where(plan == "Basic", 0.45, 0.70)
price_rise = rng.random(N) < 0.25                 # got a price increase this year

logit = (
    -1.45
    + 1.05 * (contract == "Monthly")
    - 0.045 * tenure
    - 0.075 * (logins - 10)
    + 0.33 * tickets
    + 0.55 * (payment == "Manual invoice")
    + 0.60 * price_rise
    - 0.50 * onboarded
    + 0.25 * (plan == "Basic")
)
churned = rng.random(N) < 1 / (1 + np.exp(-logit))

df = pd.DataFrame({
    "customer_id": [f"C{100000 + i}" for i in range(N)],
    "state": state,
    "industry": industry,
    "plan": plan,
    "contract_type": contract,
    "payment_method": payment,
    "seats": seats,
    "monthly_fee": monthly_fee,
    "tenure_months": tenure,
    "logins_last_30d": logins.astype(float),
    "support_tickets_90d": tickets,
    "completed_onboarding": np.where(onboarded, "Yes", "No"),
    "price_increase_last_12m": np.where(price_rise, "Yes", "No"),
    "churned": churned.astype(int),
})

# Mess: usage tracking is missing for about 3% of accounts, and a few
# payment methods were typed inconsistently in the billing system.
df.loc[rng.random(N) < 0.03, "logins_last_30d"] = np.nan
messy = rng.random(N) < 0.02
df.loc[messy, "payment_method"] = df.loc[messy, "payment_method"].str.upper()

OUT.parent.mkdir(exist_ok=True)
df.to_csv(OUT, index=False)
print(f"{len(df):,} customers written, churn rate {df.churned.mean():.1%}")
