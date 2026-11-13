"""Customer churn analysis: clean, explore, test, model and cost a retention offer.

Run:  python src/churn_analysis.py
Outputs: reports/tables/*.csv and reports/figures/*.png
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[1]
TABLES, FIGS = ROOT / "reports" / "tables", ROOT / "reports" / "figures"
TABLES.mkdir(parents=True, exist_ok=True)
FIGS.mkdir(parents=True, exist_ok=True)

BLUE, GREY, ORANGE = "#1f5a94", "#9aa5b1", "#d9822b"
plt.rcParams.update({
    "figure.dpi": 130, "font.size": 10, "axes.spines.top": False,
    "axes.spines.right": False, "axes.titleweight": "bold",
    "axes.titlesize": 12, "axes.titlelocation": "left",
})

CATEGORICAL = ["plan", "contract_type", "payment_method", "completed_onboarding",
               "price_increase_last_12m", "industry", "state"]
NUMERIC = ["tenure_months", "logins_last_30d", "support_tickets_90d", "seats"]

# Assumptions for the retention offer. These are mine, not measured.
# They are the first numbers to replace with real ones from a pilot.
OFFER_COST = 60          # dollars per contacted customer (discount plus staff time)
SAVE_RATE = 0.25         # share of would-be churners who stay because of the offer
MONTHS_SAVED = 12        # months of fee kept when a customer is saved


# ------------------------------------------------------------------ 1. clean
def load_and_clean() -> pd.DataFrame:
    df = pd.read_csv(ROOT / "data" / "subscriptions.csv")
    report = {
        "rows": len(df),
        "duplicate customer ids": int(df.customer_id.duplicated().sum()),
        "missing logins_last_30d": int(df.logins_last_30d.isna().sum()),
        "payment_method spellings before": df.payment_method.nunique(),
    }
    # The billing system stored some payment methods in capitals.
    df["payment_method"] = df.payment_method.str.capitalize()
    report["payment_method spellings after"] = df.payment_method.nunique()

    # Missing usage is filled with the median for the customer's plan.
    # A flag is kept so the model can tell a filled value from a real one.
    df["logins_missing"] = df.logins_last_30d.isna().astype(int)
    df["logins_last_30d"] = df.logins_last_30d.fillna(
        df.groupby("plan").logins_last_30d.transform("median"))

    assert df.customer_id.is_unique
    assert df[NUMERIC].notna().all().all()
    assert df.churned.isin([0, 1]).all()
    pd.Series(report, name="value").to_csv(TABLES / "01_data_quality.csv")
    print("Data quality\n", pd.Series(report).to_string(), "\n")
    return df


# ---------------------------------------------------------------- 2. explore
def churn_by_segment(df: pd.DataFrame) -> pd.DataFrame:
    df = df.assign(
        tenure_band=pd.cut(df.tenure_months, [0, 6, 12, 24, 60],
                           labels=["0-6 months", "7-12 months", "13-24 months",
                                   "25+ months"]),
        tickets_band=pd.cut(df.support_tickets_90d, [-1, 0, 1, 2, 99],
                            labels=["0 tickets", "1 ticket", "2 tickets", "3+ tickets"]),
    )
    rows = []
    for col in ["contract_type", "plan", "payment_method", "completed_onboarding",
                "price_increase_last_12m", "tenure_band", "tickets_band"]:
        g = df.groupby(col, observed=True).churned.agg(["size", "mean"]).reset_index()
        for _, r in g.iterrows():
            rows.append({"feature": col, "segment": r[col], "customers": int(r["size"]),
                         "churn_rate_pct": round(100 * r["mean"], 1)})
    out = pd.DataFrame(rows)
    out.to_csv(TABLES / "02_churn_by_segment.csv", index=False)

    fig, axes = plt.subplots(2, 3, figsize=(12, 6.2), sharey=True)
    overall = 100 * df.churned.mean()
    show = ["contract_type", "payment_method", "tenure_band",
            "tickets_band", "completed_onboarding", "price_increase_last_12m"]
    for ax, col in zip(axes.ravel(), show):
        part = out[out.feature == col]
        bars = ax.bar(part.segment.astype(str), part.churn_rate_pct, color=BLUE)
        ax.bar_label(bars, fmt="%.0f%%", padding=2, fontsize=8)
        ax.axhline(overall, color=ORANGE, ls="--", lw=1)
        ax.set_title(col.replace("_", " ").capitalize(), fontsize=10)
        ax.tick_params(axis="x", labelsize=8)
    axes[0, 0].set_ylabel("Churn rate (%)")
    axes[1, 0].set_ylabel("Churn rate (%)")
    fig.suptitle(f"Churn rate by segment (dashed line: overall {overall:.1f}%)",
                 x=0.01, ha="left", fontweight="bold")
    fig.tight_layout()
    fig.savefig(FIGS / "01_churn_by_segment.png")
    plt.close(fig)
    return out


# ------------------------------------------------------------------- 3. test
def hypothesis_tests(df: pd.DataFrame) -> pd.DataFrame:
    """Is each difference bigger than chance would give?

    Categorical columns: chi-square test of independence, with Cramer's V
    as the effect size. Numeric columns: Mann-Whitney U (the columns are
    skewed counts), with the rank-biserial correlation as the effect size.
    Twelve tests are run, so p-values are Bonferroni adjusted.
    """
    rows = []
    for col in CATEGORICAL:
        table = pd.crosstab(df[col], df.churned)
        chi2, p, _, _ = stats.chi2_contingency(table)
        v = np.sqrt(chi2 / (table.values.sum() * (min(table.shape) - 1)))
        rows.append({"feature": col, "test": "chi-square", "statistic": chi2,
                     "p_value": p, "effect_size": v, "effect_measure": "Cramer's V"})
    for col in NUMERIC + ["monthly_fee"]:
        a, b = df.loc[df.churned == 1, col], df.loc[df.churned == 0, col]
        u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
        rb = 2 * u / (len(a) * len(b)) - 1
        rows.append({"feature": col, "test": "Mann-Whitney U", "statistic": u,
                     "p_value": p, "effect_size": rb,
                     "effect_measure": "rank-biserial r"})
    out = pd.DataFrame(rows)
    out["p_adjusted"] = (out.p_value * len(out)).clip(upper=1)
    out["significant_at_0.05"] = np.where(out.p_adjusted < 0.05, "yes", "no")
    out = out.sort_values("effect_size", key=abs, ascending=False)
    out.round({"statistic": 1, "effect_size": 3}).to_csv(
        TABLES / "03_hypothesis_tests.csv", index=False)
    return out


# ------------------------------------------------------------------ 4. model
def fit_model(df: pd.DataFrame):
    features = CATEGORICAL + NUMERIC + ["logins_missing"]
    X, y = df[features], df.churned
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, stratify=y, random_state=0)

    pre = ColumnTransformer([
        ("cat", OneHotEncoder(drop="first"), CATEGORICAL),
        ("num", StandardScaler(), NUMERIC),
        ("flag", "passthrough", ["logins_missing"]),
    ])
    model = Pipeline([("pre", pre),
                      ("clf", LogisticRegression(max_iter=1000))])
    model.fit(X_train, y_train)
    proba = model.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, proba)

    names = [n.split("__", 1)[1] for n in model[:-1].get_feature_names_out()]
    coef = model[-1].coef_[0]
    odds = pd.DataFrame({"feature": names, "coefficient": coef,
                         "odds_ratio": np.exp(coef)})
    odds = odds.sort_values("coefficient", key=abs, ascending=False)
    odds.round(3).to_csv(TABLES / "04_odds_ratios.csv", index=False)

    top = odds.head(10).iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.barh(top.feature, top.odds_ratio - 1, left=1,
            color=[ORANGE if o > 1 else BLUE for o in top.odds_ratio])
    ax.axvline(1, color="black", lw=0.8)
    ax.set_xlabel("Odds ratio (above 1 raises churn, below 1 lowers it)")
    ax.set_title("Ten strongest churn drivers in the logistic model")
    fig.tight_layout()
    fig.savefig(FIGS / "02_odds_ratios.png")
    plt.close(fig)

    scored = X_test.assign(churned=y_test.values, churn_probability=proba,
                           monthly_fee=df.loc[X_test.index, "monthly_fee"])
    return scored, odds, auc


# ----------------------------------------------------- 5. lift and offer cost
def lift_and_business_case(scored: pd.DataFrame):
    scored = scored.sort_values("churn_probability", ascending=False).reset_index(drop=True)
    scored["decile"] = pd.qcut(scored.index, 10, labels=range(1, 11)).astype(int)
    base = scored.churned.mean()

    lift = scored.groupby("decile").agg(
        customers=("churned", "size"), churners=("churned", "sum"),
        churn_rate=("churned", "mean"),
        avg_probability=("churn_probability", "mean")).reset_index()
    lift["lift"] = lift.churn_rate / base
    lift["cumulative_churners_pct"] = 100 * lift.churners.cumsum() / lift.churners.sum()
    lift.round(3).to_csv(TABLES / "05_lift_by_decile.csv", index=False)

    fig, ax = plt.subplots(figsize=(8, 4))
    bars = ax.bar(lift.decile, 100 * lift.churn_rate, color=BLUE)
    ax.bar_label(bars, fmt="%.0f%%", padding=2, fontsize=8)
    ax.axhline(100 * base, color=ORANGE, ls="--", lw=1)
    ax.text(10.4, 100 * base + 1, f"overall {100 * base:.0f}%", ha="right",
            color=ORANGE, fontsize=9)
    ax.set_xticks(lift.decile)
    ax.set_xlabel("Risk decile on the holdout set (1 = highest predicted risk)")
    ax.set_ylabel("Actual churn rate (%)")
    ax.set_title("Actual churn by predicted risk decile")
    fig.tight_layout()
    fig.savefig(FIGS / "03_lift_by_decile.png")
    plt.close(fig)

    # Net value of contacting the top k deciles with the retention offer.
    def campaign(saved_share: float, cost: float) -> pd.DataFrame:
        rows = []
        for k in range(1, 11):
            t = scored[scored.decile <= k]
            churners = t[t.churned == 1]
            revenue_saved = saved_share * churners.monthly_fee.sum() * MONTHS_SAVED
            spend = cost * len(t)
            rows.append({"deciles_contacted": k, "customers_contacted": len(t),
                         "churners_reached": len(churners),
                         "revenue_saved": revenue_saved, "offer_cost": spend,
                         "net_value": revenue_saved - spend,
                         "roi_pct": 100 * (revenue_saved - spend) / spend})
        return pd.DataFrame(rows)

    plan = campaign(SAVE_RATE, OFFER_COST)
    plan.round(0).to_csv(TABLES / "06_campaign_by_depth.csv", index=False)

    # Sensitivity: the best net value under other save rates and offer costs.
    sens = pd.DataFrame(
        [[campaign(s, c).net_value.max() for c in (40, 60, 80, 100)]
         for s in (0.10, 0.15, 0.25, 0.35)],
        index=[f"save rate {int(s * 100)}%" for s in (0.10, 0.15, 0.25, 0.35)],
        columns=[f"cost ${c}" for c in (40, 60, 80, 100)]).round(0)
    sens.to_csv(TABLES / "07_sensitivity.csv")

    fig, ax = plt.subplots(figsize=(8, 4))
    best = plan.net_value.idxmax()
    ax.bar(plan.deciles_contacted, plan.net_value / 1000,
           color=[ORANGE if i == best else BLUE for i in plan.index])
    ax.set_xticks(plan.deciles_contacted)
    ax.set_xlabel("Number of risk deciles contacted (starting with the riskiest)")
    ax.set_ylabel("Net value on the holdout set ($ thousand)")
    ax.set_title("Net value of the retention offer by campaign depth")
    fig.tight_layout()
    fig.savefig(FIGS / "04_campaign_net_value.png")
    plt.close(fig)
    return lift, plan, sens


def main() -> None:
    pd.set_option("display.width", 170)
    df = load_and_clean()
    print(f"Overall churn rate: {df.churned.mean():.1%} "
          f"({df.churned.sum():,} of {len(df):,})\n")
    seg = churn_by_segment(df)
    print(seg.to_string(index=False), "\n")
    tests = hypothesis_tests(df)
    print(tests.to_string(index=False), "\n")
    scored, odds, auc = fit_model(df)
    print(f"Holdout ROC AUC: {auc:.3f} on {len(scored):,} customers\n")
    print(odds.round(3).to_string(index=False), "\n")
    lift, plan, sens = lift_and_business_case(scored)
    print(lift.round(3).to_string(index=False), "\n")
    print(plan.round(0).to_string(index=False), "\n")
    print(sens.to_string())
    print(f"\nMonthly fee lost to churn in holdout: "
          f"${scored.loc[scored.churned == 1, 'monthly_fee'].sum():,.0f} per month")


if __name__ == "__main__":
    main()
