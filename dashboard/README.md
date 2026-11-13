# Dashboard build pack: customer churn

This folder holds what is needed to build the churn dashboard in Power BI and in Tableau. The dashboards themselves are not built yet. Power BI Desktop needs Windows, and neither tool was installed on the machine where the analysis was written.

## Files

| File | Use |
|---|---|
| `data/customers_scored.csv` | One row per customer, 7,000 rows, with bands, churn probability and risk decile |
| `measures.dax` | Power BI measures |
| `portfolio_theme.json` | Power BI colour theme |

The CSV is written by `python src/export_dashboard_data.py`. The script checks that the test-set deciles match the lift table from the analysis.

## Columns added for the dashboard

| Column | Meaning |
|---|---|
| `tenure_band`, `tickets_band` | Bands used in the segment charts |
| `churn_probability` | Score from the logistic model |
| `dataset` | Train or Test. The model was trained on the Train rows |
| `risk_decile` | 1 is the riskiest tenth, ranked inside each dataset |
| `annual_fee` | Monthly fee times 12 |

Scores for Train customers are in-sample. Pages 2 and 3 should be filtered to `dataset = Test`, otherwise the model looks better than it is.

## Pages

### Page 1. Who churns

| Visual | Fields |
|---|---|
| Cards | Customers, Churned Customers, Churn Rate %, Monthly Fee Lost |
| Six bar charts | Churn Rate % by `contract_type`, `payment_method`, `tenure_band`, `tickets_band`, `completed_onboarding`, `price_increase_last_12m`. Add Overall Churn Rate % as a constant line |
| Slicers | `plan`, `industry`, `state` |

Sort `tenure_band` and `tickets_band` by hand so the bands run in order.

### Page 2. Risk model (Test customers only)

| Visual | Fields |
|---|---|
| Column chart | `risk_decile` on the axis, Churn Rate % as the value, Overall Churn Rate % as a line |
| Column chart | `risk_decile` on the axis, Lift as the value |
| Table | The 50 customers with the highest `churn_probability`, with plan, contract type, tenure and monthly fee |

### Page 3. Retention offer (Test customers only)

| Visual | Fields |
|---|---|
| Slicers | Save Rate and Offer Cost what-if parameters |
| Column chart | `risk_decile` on the axis, Net Value Cumulative as the value |
| Table | `risk_decile`, Customers Contacted Cumulative, Net Value Cumulative, Campaign ROI % |

The chart reads as "net value if the campaign contacts this decile and every riskier one".

## Tableau

Connect to `customers_scored.csv`. Create two parameters, `Save Rate` (float, 0.05 to 0.5, default 0.25) and `Offer Cost` (integer, 20 to 120, default 60). Then create these calculated fields.

| Name | Formula |
|---|---|
| Churn Rate % | `SUM([Churned]) / COUNT([Customer Id])` |
| Overall Churn Rate % | `{ FIXED [Dataset] : SUM([Churned]) / COUNT([Customer Id]) }` |
| Lift | `[Churn Rate %] / MIN([Overall Churn Rate %])` |
| Monthly Fee Lost | `SUM(IF [Churned] = 1 THEN [Monthly Fee] END)` |
| Net Value | `[Save Rate] * SUM(IF [Churned] = 1 THEN [Annual Fee] END) - [Offer Cost] * COUNT([Customer Id])` |
| Net Value Cumulative | `RUNNING_SUM([Net Value])` computed along `Risk Decile` |

`Overall Churn Rate %` is fixed on `Dataset`, so slicers on plan or industry will not change it unless they are added to context.

## Numbers the dashboard must match

| Measure | Filter | Value |
|---|---|---|
| Customers | None | 7,000 |
| Churn rate | None | 26.2% |
| Churn rate, monthly contract | None | 33.4% |
| Customers and churners | Test | 1,750 and 458 |
| Churn rate in decile 1 | Test | 57.7% |
| Lift in decile 1 | Test | 2.2 |
| Net Value Cumulative at decile 5 | Test, save rate 0.25, offer cost 60 | $15,198 |
| Net Value Cumulative at decile 10 | Test, save rate 0.25, offer cost 60 | -$12,176 |
