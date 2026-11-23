# Real-browser tests
`cd backend/tests/browser_e2e && npm install && cd ../.. && python tests/browser_e2e/run_browser_e2e.py`
Starts a throw-away server with synthetic data (a published batch containing FULLY_VERIFIED, HALL_LIST_CONFIRMED and UNRESOLVED records) and drives headless Chromium (`@sparticuz/chromium` via npm, no download from other hosts). Result at release: 262 passed, 0 failed.
On a normal desktop you may instead point `executablePath` at an installed Chrome. `node_modules` is not shipped.
