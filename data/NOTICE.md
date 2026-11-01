# Data notice

VintageBench uses the **Real-Time Data Set for Macroeconomists (RTDSM)** of the Federal
Reserve Bank of Philadelphia. **This repository contains no RTDSM data.** Users download
the files themselves with `python scripts/fetch_data.py`, which stores them in
`data/raw/` (gitignored) and checks them against `data/checksums.json`. That file holds
only SHA-256 hashes and counts, never data values.

The MIT License in [LICENSE](../LICENSE) covers the VintageBench code only. It does not
cover the RTDSM data or the underlying agency data.

## Source

- Federal Reserve Bank of Philadelphia, Real-Time Data Set for Macroeconomists,
  https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/real-time-data-set-for-macroeconomists
- Variables (files and variable pages are listed in [README.md](README.md)): EMPLOY
  (nonfarm payroll employment), ROUTPUT (real GDP), IPT (industrial production index,
  total), RUC (civilian unemployment rate), PCPI (consumer price index, monthly vintages).
- Original sources, per the RTDSM documentation: U.S. Bureau of Labor Statistics
  (EMPLOY, RUC, PCPI), U.S. Bureau of Economic Analysis (ROUTPUT), and the Board of
  Governors of the Federal Reserve System (IPT, from the G.17 release).
- Accessed 2026-11-01. The pinned vintage range is in `data/manifest.json`.

## Terms of use (quoted verbatim, accessed 2026-11-01)

The RTDSM pages fall under the Philadelphia Fed's "Online Terms of Use and Privacy
Notice", https://www.philadelphiafed.org/about-us/privacy-notice:

- Scope: "By using this website or the information, materials, or other content
  available on or through it, you agree that such use is governed by the following
  terms, which include our privacy policy. We reserve the right to change these terms
  without notice."
- Appropriate Use: "The content provided on this website may be used for
  informational, educational, and research purposes only."
- "Some of the content on this website may be copyrighted. Permission to use such
  copyrighted material must be obtained from the owner."
- "We do not permit the use of our name in any advertising, as an endorsement for any
  product or service, or for any other commercial purpose."
- "You may not access this website in a manner that could interfere with or disrupt the
  site. Without limiting the foregoing, you may not engage in excessive access to the
  website in a way that could adversely affect the site for others. We reserve the
  right to restrict such activity in our discretion."
- Disclaimer: "We assume no liability or responsibility for the accuracy, correctness,
  completeness, or timeliness of any content available on or through this website, nor
  do we represent that the use of such content will not infringe privately held
  rights. All content available on or through this website is provided on an “as is,”
  “as available” basis."

The RTDSM page itself
(https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/real-time-data-set-for-macroeconomists)
says: "The real-time data set consists of vintages, or snapshots, of time series of
major macroeconomic variables. The data set may be used by macroeconomic researchers to
verify empirical results, to analyze policy, or to forecast. All data are updated at
the end of each month."

### What this means for VintageBench

- **Allowed:** use for informational, educational and research purposes. VintageBench
  is a non-commercial research benchmark that evaluates AI models. We read that as a
  research purpose. The terms do not mention AI or machine-learning use at all, either
  to allow it or to forbid it.
- **Redistribution:** none of the pages we read grants permission to redistribute. The
  terms also warn that some content "may be copyrighted". So VintageBench does not
  redistribute: no xlsx, parquet or data values are committed (SPEC §2.3). Tasks store
  only definitions. Golds are computed locally from the user's own download. Committed
  results are aggregate metrics only.
- **No endorsement:** the Federal Reserve Bank of Philadelphia, BLS, BEA and the
  Federal Reserve Board do not sponsor or endorse VintageBench and are not affiliated
  with it. Their names are used only to attribute the data. The data are used "as is",
  with no warranty of accuracy, completeness or timeliness.
- **Polite access:** `scripts/fetch_data.py` downloads five files one after another,
  with pauses, a timeout and a few retries. It identifies itself with a VintageBench
  User-Agent and does not download again if the files are already present.

## Citation

Following the RTDSM page ("This is the preferred article to cite for technical journal
articles"):

- Croushore, Dean, and Tom Stark. "A Real-Time Data Set for Macroeconomists." *Journal
  of Econometrics* 105 (November 2001), pp. 111-130.

Dataset citation (our format; the Philadelphia Fed does not specify one):

- Federal Reserve Bank of Philadelphia. Real-Time Data Set for Macroeconomists:
  EMPLOY, ROUTPUT, IPT, RUC and PCPI, vintages from December 2015 (RUC: 2015 Q4)
  through the pinned vintages in `data/manifest.json`. Accessed November 1, 2026.
  https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/real-time-data-set-for-macroeconomists

Please also credit the original agencies: U.S. Bureau of Labor Statistics, U.S. Bureau
of Economic Analysis, and Board of Governors of the Federal Reserve System.

## Why not FRED/ALFRED

VintageBench v0 used vintages from ALFRED (Federal Reserve Bank of St. Louis), obtained
through the FRED API, and committed them to the repository. The FRED terms forbid
storing or caching FRED content and forbid using the API in connection with
machine-learning or LLM development. v1 therefore removed all FRED-derived data, the
v0 tasks that contained values, and the run caches, and moved to RTDSM. No FRED data
or FRED API code remains (SPEC §8).
