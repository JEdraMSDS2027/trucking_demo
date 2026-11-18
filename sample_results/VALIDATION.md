# Verification

Verified on 4 November 2026 using Python 3.12 and the versions recorded in `requirements-lock.txt`.

- 13 automated checks passed, including Streamlit dashboard rendering, form submission, stale-data handling, hard exclusions, dimensions/axle limits, unique truck/load allocation, shared ferry slots, recovery timing, revenue exceptions, verified-history training and cost reconciliation.
- The local Streamlit health endpoint returned HTTP 200.
- The live dashboard was inspected in the browser. Initial metric clipping was corrected with shorter unit labels and smaller metric typography.
- The default seed 42 allocation was regenerated after the final model changes; it retains the results in `summary.json` and `RESULTS.md`.

`test_results.xml` contains the final successful test report. Verification uses synthetic data and does not certify real-world operational feasibility or predictive performance.
