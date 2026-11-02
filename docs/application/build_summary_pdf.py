"""Build docs/application/summary.pdf (2 pages) from the numbers in results/PILOT.md.

Run: python docs/application/build_summary_pdf.py
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT = Path(__file__).parent / "summary.pdf"

ss = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=16, leading=19, spaceAfter=4)
SUB = ParagraphStyle(
    "sub",
    parent=ss["Normal"],
    fontSize=9,
    leading=11,
    textColor=colors.HexColor("#444444"),
    alignment=TA_LEFT,
)
H2 = ParagraphStyle(
    "h2",
    parent=ss["Heading2"],
    fontSize=11.5,
    leading=14,
    spaceBefore=7,
    spaceAfter=3,
    textColor=colors.HexColor("#1f3a5f"),
)
P = ParagraphStyle("p", parent=ss["Normal"], fontSize=9.2, leading=12, spaceAfter=4)
B = ParagraphStyle("b", parent=P, leftIndent=10, bulletIndent=2, spaceAfter=2)
SMALL = ParagraphStyle("s", parent=P, fontSize=8, leading=10, textColor=colors.HexColor("#555555"))


def bullets(items):
    return [Paragraph(t, B, bulletText="•") for t in items]


CELL = ParagraphStyle("cell", parent=ss["Normal"], fontSize=8.2, leading=9.6)
CELLB = ParagraphStyle("cellb", parent=CELL, fontName="Helvetica-Bold")


def table(rows, widths):
    rows = [[Paragraph(str(c), CELLB if i == 0 else CELL) for c in r] for i, r in enumerate(rows)]
    t = Table(rows, colWidths=widths, hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), "Helvetica", 8.2),
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.2),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b0b8c4")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return t


def page1():
    s = [
        Paragraph("VintageBench: Do AI Analysts Update Correctly When the Data Are Revised?", H1),
        Paragraph(
            "Divya Jyoti, MIMS (AI &amp; Data Science), UC Berkeley · "
            "github.com/divyajyoti-dev/vintagebench-release · "
            "6 months, Nov 2026 – Apr 2027",
            SUB,
        ),
        Spacer(1, 6),
        Paragraph("Problem", H2),
        Paragraph(
            "Analysts and AI agents draw conclusions from provisional data such as "
            "first-release GDP, payrolls and industrial production, which statistical "
            "agencies later revise. A trustworthy analyst agent must answer from the data "
            "available on the date in question, judge how fragile its conclusion is, and "
            "update when, and only when, revisions change it.",
            P,
        ),
        Paragraph("Task format and grading", H2),
    ]
    s += bullets(
        [
            "Plain yes/no questions with an as-of date, e.g. <i>“Did US real GDP shrink in "
            "2022 Q2?”</i>. In turn 1 a <b>tool serves only the vintage published by that "
            "date</b>. The reply gives the calculation, the answer, the confidence, and the "
            "<b>probability the conclusion survives full revision</b>.",
            "Turn 2 is neutral: <i>“Here is the latest data. Answer the question.”</i> The "
            "tasks are flips (the conclusion changes on revision), controls, and no-change "
            "tasks (the turn-2 data are identical).",
            "Gold answers are computed from the vintages by code, with no human labels and "
            "no LLM judge. Metrics: as-of and revised accuracy; update correctness (actual "
            "answer change); survival calibration and discrimination; leakage; label/text "
            "contradiction; and a no-tools memorization probe. Sanity agents validate the "
            "grader.",
            "Data: Philadelphia Fed Real-Time Data Set for Macroeconomists (BLS, BEA and "
            "Federal Reserve Board series). It is fetched by a checksummed script, so no "
            "raw data are redistributed. A v0 prototype used ALFRED.",
        ]
    )
    s += [
        Paragraph("Pilot (v1): 45 tasks × 4 OpenAI configs × 3 trials = 540 episodes, $2.83", H2),
        Paragraph(
            "<b>Base rate.</b> Of 1,235 candidate questions, 120 (9.7%) first-release "
            "conclusions differ on the latest vintage. For the payroll 3-month-average "
            "&gt;150k template it is 23/116 (19.8%).",
            P,
        ),
        Paragraph(
            "<b>Calibration.</b> Mean survival probabilities were 0.86–0.92, close to the "
            "~90% survival the base rate implies. But they barely separate conclusions "
            "that later flipped from "
            "those that held (AUC flip vs non-flip, with ties counting half):",
            P,
        ),
        table(
            [
                [
                    "Config",
                    "Mean survival prob., flips",
                    "Mean, non-flips",
                    "AUC",
                    "Flips rated ≥ 0.8",
                    "As-of correct",
                    "Update correct (flips)",
                ],
                ["gpt-6-sol / reasoning off", "0.85", "0.88", "0.61", "48/60", "135/135", "60/60"],
                ["gpt-6-sol / medium", "0.85", "0.89", "0.58", "45/60", "135/135", "60/60"],
                ["gpt-6-luna / reasoning off", "0.86", "0.95", "0.64", "53/60", "109/135", "41/60"],
                ["gpt-6-luna / medium", "0.91", "0.93", "0.60", "54/59", "133/135", "59/60"],
            ],
            [
                1.6 * inch,
                1.0 * inch,
                0.75 * inch,
                0.45 * inch,
                0.85 * inch,
                0.8 * inch,
                0.75 * inch,
            ],
        ),
        Spacer(1, 4),
        Paragraph(
            "<b>Memorization (no tools).</b> Recalls that matched a vintage matched the "
            "first release far more often than the latest: 71 vs 17 of 324 "
            "distinguishable values. Many matches are on low-precision quantities, where "
            "they can be chance. With tools, leakage was 0/540.",
            P,
        ),
    ]
    return s


def page2():
    s = [
        Paragraph("Lessons", H2),
    ]
    s += bullets(
        [
            "v0 showed that frontier models ace questions that spell out the formula. On "
            "v1’s plain questions the frontier model is still at 135/135. The small model "
            "with reasoning off failed mainly at data gathering (20 of 26 wrong answers). "
            "Accuracy alone therefore misses the hard part: <b>judgement about revisions</b>.",
            "With the calculation placed before the answer, label/text contradictions "
            "dropped to 0 of 1,080 turns. In v0 they were the main error source.",
            "Limits: small n, a thin flip pool, only OpenAI models, and survival scored "
            "against the latest pinned vintage.",
        ]
    )
    s += [
        Paragraph("Expected outputs and impact", H2),
        Paragraph(
            "An open benchmark of ~600 tasks over more series, revision horizons and "
            "multi-step analyses; the tool-serving harness; base-rate tables; leaderboard "
            "results for frontier and open-weight models; and a paper. Agents used in "
            "economic, financial and policy analysis need to know when their conclusions "
            "are provisional. The same design generalizes to <b>earnings restatements, "
            "corrected clinical data and data-pipeline backfills</b>.",
            P,
        ),
        Paragraph("How it differs", H2),
        Paragraph(
            "<i>Total Recall?</i> (Crane, Karra &amp; Soto, FRB FEDS 2025-044, June 2025) "
            "shows that LLM recall mixes first-print data with later revisions, and that "
            "LLMs often believe they have data not yet released. It probes memory. "
            "VintageBench tests agents working from dated, tool-served vintages, and "
            "whether they update correctly. ExAnte (arXiv:2505.19533) and "
            "Look-Ahead-Bench (arXiv:2601.13770) measure temporal leakage. LongDS-Bench "
            "(arXiv:2605.30434) and TrustDABench (arXiv:2608.24145) test analytical state "
            "and robustness. None uses real data vintages.",
            P,
        ),
        Paragraph("Methodology and request", H2),
    ]
    s += bullets(
        [
            "<b>Expert data:</b> economists and statistical-agency analysts review the "
            "templates and gold conventions, write harder multi-step questions, and rate "
            "which revisions an expert would anticipate, giving a human survival baseline.",
            "<b>Snorkel support:</b> engineering for task generation at scale, hosting, a "
            "leaderboard, and restatement and clinical-data harness extensions.",
            "<b>Credits: $2,000.</b> The costliest pilot configuration cost $1.52 for 135 "
            "episodes ($0.0113 each). 600 tasks × 3 trials × 10 configs ≈ $203 per pass. "
            "Five passes come to $1,017, doubled for longer agentic tasks.",
        ]
    )
    s += [
        Paragraph("Milestones", H2),
        table(
            [
                ["Nov 2026", "Dec 2026 – Jan 2027", "Feb 2027", "Mar 2027", "Apr 2027"],
                [
                    "Expert review; more series",
                    "600 tasks; open-weight models",
                    "Restatement and clinical pilots",
                    "Human baseline; leaderboard",
                    "Paper; public release",
                ],
            ],
            [1.4 * inch] * 5,
        ),
        Paragraph("Team", H2),
        Paragraph(
            "Divya Jyoti (lead): MIMS (AI &amp; Data Science), UC Berkeley. About 3 years "
            "of software engineering in quantitative finance at UBS. Built an evaluation "
            "framework for a text-to-SQL data-analysis agent during an industry "
            "internship. Open to a Snorkel co-advisor.",
            P,
        ),
        Spacer(1, 6),
        Paragraph(
            "Data: Federal Reserve Bank of Philadelphia, Real-Time Data Set for "
            "Macroeconomists (Croushore &amp; Stark, J. Econometrics 2001). The Bank and "
            "the source agencies do not endorse this work.",
            SMALL,
        ),
    ]
    return s


def main() -> None:
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title="VintageBench summary",
        author="Divya Jyoti",
    )
    doc.build(page1() + [PageBreak()] + page2())
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
