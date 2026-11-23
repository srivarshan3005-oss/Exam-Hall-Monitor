# Free permanent link with GitHub Pages (static copy)

GitHub Pages cannot run the Python server, so this project can publish a **static copy** of the student portal:

* `backend\build_static_site.py` reads your database and stored PDFs and writes the `site\` folder:
  the portal files, one JSON file per register number (the same answer the live API gives), `published.json`/`status.json`,
  and **one plain image per used PDF page**. The yellow highlight of the searched number is drawn in the browser.
* `publish_site.bat` builds it, then `publish_site.ps1` pushes it to the `gh-pages` branch in small batches (one big push is rejected by GitHub with HTTP 408). The `site\\` folder keeps its own `.git`, so later publishes upload only changed files, and a failed run can simply be run again.
* One-time GitHub setting: **Settings -> Pages -> Build and deployment -> Source: Deploy from a branch -> Branch: gh-pages, folder: / (root) -> Save.**
* Link: `https://<github-user>.github.io/<repository>/`

## What differs from the live server
* It is a snapshot. Data changes only when `publish_site.bat` runs again (the server must be running so it keeps scanning the college site).
* Every register number's data file is public; anyone can download them all. The source PDFs are already public on the college site.
* No server-side limit on failed searches, no `/api`, no admin pages. "Print slip" prints the page.
* GitHub Pages limits (published site <= 1 GB, soft 100 GB/month bandwidth, no commercial use) apply. The builder prints a warning near 900 MB.

## Refresh automatically (optional, Windows)
`schtasks /create /sc minute /mo 30 /tn ExamMonitorPublish /tr "C:\ExamMonitor\publish_site.bat"` (the laptop and the server must be on).

## Fully automatic version (no laptop, no start.bat)
`.github/workflows/publish-pages.yml` does everything on GitHub's servers every 30 minutes: read the official VSB notice page, download and parse new PDFs, build the static portal and publish it.

One-time setup:
1. Push this project to the `main` branch of your repository.
2. Settings -> Pages -> Build and deployment -> Source: **GitHub Actions** (not "Deploy from a branch").
3. Actions tab -> "Publish student portal (automatic)" -> Run workflow (the first run downloads and parses everything, so it takes a while).

Safety: if the official site cannot be read or no allotment is found, nothing is deployed and the last good site stays online. The old `gh-pages` branch is no longer used and can be deleted.
Limits: GitHub's schedule is best effort (late runs happen); scheduled workflows stop after 60 days without repository activity.
