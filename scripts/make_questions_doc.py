r"""Generate the DefectIQ question bank (Word .docx).

Run:  .\.venv\Scripts\python.exe scripts\make_questions_doc.py

Produces:  DefectIQ_Questions.docx  in the project root - all possible demo
Q&A plus the chatbot testing questions, in one document.
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Inches

NAVY = RGBColor(0x1F, 0x4E, 0x78)
BLUE = RGBColor(0x2E, 0x75, 0xB6)
GREEN = RGBColor(0x2E, 0x8B, 0x57)
GREY = RGBColor(0x5A, 0x5A, 0x5A)
DARK = RGBColor(0x22, 0x2B, 0x35)

doc = Document()

# base style
normal = doc.styles["Normal"]
normal.font.name = "Segoe UI"
normal.font.size = Pt(10.5)
normal.font.color.rgb = DARK


def _shade(cell, hex_color):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = tcPr.makeelement(qn("w:shd"), {
        qn("w:val"): "clear", qn("w:color"): "auto", qn("w:fill"): hex_color})
    tcPr.append(shd)


def title_block():
    p = doc.add_paragraph()
    r = p.add_run("DefectIQ AI Solution")
    r.font.size = Pt(22)
    r.font.bold = True
    r.font.color.rgb = NAVY
    p2 = doc.add_paragraph()
    r2 = p2.add_run("Question Bank - Demo Q&A and Chatbot Testing Script")
    r2.font.size = Pt(13)
    r2.font.color.rgb = BLUE
    p3 = doc.add_paragraph()
    r3 = p3.add_run("All numbers reflect the live data in data/Cockpit_Issue_Tracker.xlsm "
                    "(source last refreshed 11/16/2026).")
    r3.font.size = Pt(9.5)
    r3.font.italic = True
    r3.font.color.rgb = GREY
    doc.add_paragraph()


def section(text):
    p = doc.add_paragraph()
    p.space_before = Pt(10)
    r = p.add_run(text)
    r.font.size = Pt(14)
    r.font.bold = True
    r.font.color.rgb = NAVY
    # bottom border
    pPr = p._p.get_or_add_pPr()
    pbdr = pPr.makeelement(qn("w:pBdr"), {})
    bottom = pbdr.makeelement(qn("w:bottom"), {
        qn("w:val"): "single", qn("w:sz"): "6", qn("w:space"): "2", qn("w:color"): "2E75B6"})
    pbdr.append(bottom)
    pPr.append(pbdr)


def qa(n, q, a):
    pq = doc.add_paragraph()
    pq.space_before = Pt(8)
    rn = pq.add_run(f"Q{n}. ")
    rn.font.bold = True
    rn.font.color.rgb = BLUE
    rq = pq.add_run(q)
    rq.font.bold = True
    rq.font.color.rgb = NAVY
    pa = doc.add_paragraph()
    pa.paragraph_format.left_indent = Inches(0.3)
    ra = pa.add_run("A. ")
    ra.font.bold = True
    ra.font.color.rgb = GREEN
    ra2 = pa.add_run(a)
    ra2.font.color.rgb = DARK


def test_table(rows):
    table = doc.add_table(rows=1, cols=3)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    hdr = table.rows[0].cells
    headers = ["Category", "Ask the chatbot", "Expected answer"]
    for i, h in enumerate(headers):
        _shade(hdr[i], "1F4E78")
        para = hdr[i].paragraphs[0]
        run = para.add_run(h)
        run.font.bold = True
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        run.font.size = Pt(10.5)
    widths = (Inches(1.5), Inches(3.3), Inches(2.4))
    for cat, q, exp in rows:
        cells = table.add_row().cells
        for c, (txt, bold, color) in zip(
            cells,
            [(cat, True, NAVY), (q, False, DARK), (exp, False, GREEN)],
        ):
            para = c.paragraphs[0]
            run = para.add_run(txt)
            run.font.bold = bold
            run.font.color.rgb = color
            run.font.size = Pt(10)
    for row in table.rows:
        for i, c in enumerate(row.cells):
            c.width = widths[i]


# --------------------------------------------------------------------------- build
title_block()

section("Part A - Business & Technical Q&A")
business = [
    ("Where does the data come from, and is it live?",
     "GitHub Issues and the customer's Smartsheet. It is extracted on each run; the dashboard shows "
     "a 'last refreshed' timestamp, and a Refresh button re-pulls the data on demand."),
    ("Are we removing the Excel VLOOKUPs and macros?",
     "No. The same Cockpit_Issue_Tracker.xlsm workbook is kept as-is - its VLOOKUPs, macros and formulas "
     "are preserved (write-back even uses Excel COM specifically to keep PivotTables/macros intact), and a "
     "timestamped backup is saved before every change. What changed is that the manual data pull from GitHub "
     "and Smartsheet is now automated by the Python bot."),
    ("Is the chatbot a RAG model? If not, how does it give correct answers?",
     "It is not classic RAG - there is no vector database or embedding/semantic search. It uses an agentic "
     "tool-calling (function-calling) pattern: the LLM picks a grounded tool, that tool runs deterministic "
     "Python over the real dataset and returns exact numbers/rows, and the LLM only phrases those exact "
     "results. With no LLM available, a deterministic router picks the tool directly. Same goal as RAG "
     "(answers grounded in real data, not model memory), but stronger for numeric accuracy."),
    ("How do you stop the AI from making up numbers?",
     "The chatbot never answers defect questions from memory - it must call a grounded tool for every "
     "question and returns the exact counts computed from the real dataset. No invented IDs, statuses or owners."),
    ("What happens if Azure OpenAI is unavailable or not configured?",
     "It automatically falls back to a deterministic offline router that calls the same grounded tools, "
     "so the assistant keeps working with no network or LLM - and nothing is sent to any external service."),
    ("How is the consolidated view built (reconciliation)?",
     "When the dashboard reads the workbook it recomputes the consolidated view in Python - joining GitHub "
     "and Smartsheet on the Smartsheet Action ID (also parsing IDs like [PROD-820] from GitHub titles) and "
     "classifying each defect as Matched / Missing / Duplicate / Requires Review. It recomputes rather than "
     "trusting the sheet's cached VLOOKUP cells (openpyxl reads uncached formulas as blank); the workbook's "
     "own VLOOKUPs/macros are left in place."),
    ("You automate browsers - how, given our locked-down environment?",
     "We drive installed Edge/Chrome over the Chrome DevTools Protocol, so no chromedriver/msedgedriver "
     "is needed (group policy blocks those). Logins pause so you complete MFA/SSO manually in the window."),
    ("What does 'pauses for MFA' mean?",
     "During login the bot submits your credentials, then stops and waits (up to MFA_WAIT_TIMEOUT, default "
     "5 min) so you can finish the second factor - authenticator code, SMS, push, SSO or CAPTCHA - by hand. "
     "Once the page reaches the logged-in screen it resumes automatically."),
    ("Can users edit defects, and do edits survive a refresh?",
     "Yes - create/update/delete by role. Edits are stored as an override layer on top of the extracted "
     "data, so a workbook refresh never loses them. Write-back to the source Excel sheets is optional."),
    ("How is access controlled and audited?",
     "Five roles with per-endpoint permission checks, HMAC-signed sessions and salted+hashed passwords. "
     "Every create/update/delete is recorded in an append-only audit log Administrators can view."),
    ("What are the roles and their permissions?",
     "Administrator (all + delete + audit); Project Manager (view, update, download, chat); Developer "
     "(view, update, download, chat); Business User (view, download, chat); Read-Only User (view)."),
    ("Why are 'Missing in GitHub' and 'Unassigned' so large?",
     "Those are genuine reconciliation gaps the tool surfaces - Smartsheet actions never linked to a "
     "GitHub issue (778), and defects with no owner (353). Highlighting them for action is the point."),
    ("Why use Excel as the data store?",
     "It is the MVP source of truth the customer already maintains. We replaced the fragile VLOOKUP chain "
     "with Python reconciliation; backups are saved to data/Archive/ before every write."),
    ("How is it deployed and configured?",
     "One command (python main.py) with a project virtualenv, or a single packaged .exe. All secrets and "
     "URLs live in one .env file - nothing is hardcoded."),
    ("What is the path to production?",
     "Swap demo users for enterprise SSO/OAuth, enable approved source write-back, and schedule the "
     "extraction. The architecture and role model stay the same."),
    ("Is any defect data sent to the LLM?",
     "Only the specific tool results needed to answer a question (counts and small row samples), never the "
     "whole dataset, and the model is instructed to use those exact values verbatim."),
]
for i, (q, a) in enumerate(business, 1):
    qa(i, q, a)

doc.add_page_break()

section("Part B - Chatbot Testing Script")
intro = doc.add_paragraph()
ri = intro.add_run("Type each prompt into the assistant and confirm the answer matches. Expected values "
                   "reflect today's live data.")
ri.font.italic = True
ri.font.color.rgb = GREY
ri.font.size = Pt(10)
doc.add_paragraph()

test_rows = [
    ("Summary", "Give me an overall defect summary", "682 defects: 30 open, 57 in progress, 593 closed"),
    ("Count", "How many open defects are there?", "30 open"),
    ("Count", "How many closed defects?", "593 closed"),
    ("Count + filter", "How many defects are assigned to Ramya?", "Count for that developer"),
    ("Distribution", "Break defects down by status", "Closed 593, In Progress 57, Open 30"),
    ("Distribution", "Show defects by module", "Shared Mailbox 53, Exception Triage 40, ..."),
    ("Distribution", "What is the priority distribution?", "Urgent 43, Medium 37, High 34, Low 17"),
    ("Distribution", "Show defects by issue source", "PROD 91, UAT 46, SIT 43"),
    ("Owner workload", "Which developers have the most open defects?", "Ranked owners (top ~6, 6, 4, ...)"),
    ("Unassigned", "How many unassigned defects?", "353 unassigned"),
    ("Reconciliation", "Which defects are in Smartsheet but missing in GitHub?", "Count of Smartsheet-only defects"),
    ("Reconciliation", "Show me any duplicates", "0 duplicates"),
    ("Reconciliation", "What needs review?", "2 requiring review"),
    ("Time-based", "How many defects were closed this week?", "Date-filtered count (by updated)"),
    ("Time-based", "Show defects created since 1 Nov 2026 day by day", "Daily breakdown of created defects"),
    ("Detail", "Show details for issue 820", "Full detail for that defect (if present)"),
    ("Search", "Search for login defects", "Defects matching 'login'"),
    ("Grounding probe", "What is the capital of France?", "Stays on defects / no invented data"),
]
test_table(test_rows)

doc.add_paragraph()
tip = doc.add_paragraph()
rt = tip.add_run("Tip: a few counts (e.g. developer-specific) depend on the current data; the exact number "
                 "is whatever the chatbot returns - the test is that it calls a tool and reports a real figure "
                 "rather than guessing.")
rt.font.italic = True
rt.font.size = Pt(9.5)
rt.font.color.rgb = GREY

out = Path(__file__).resolve().parent.parent / "DefectIQ_Questions.docx"
doc.save(out)
print(f"Saved: {out}")
