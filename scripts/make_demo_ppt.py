r"""Generate the DefectIQ AI Solution demo deck (PowerPoint) - short version.

Run:  .\.venv\Scripts\python.exe scripts\make_demo_ppt.py

Produces:  DefectIQ_Demo.pptx  in the project root (6 slides).
KPI numbers are the live values read from data/Cockpit_Issue_Tracker.xlsm.
"""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

# --------------------------------------------------------------------------- theme
NAVY = RGBColor(0x1F, 0x4E, 0x78)
BLUE = RGBColor(0x2E, 0x75, 0xB6)
TEAL = RGBColor(0x17, 0xA2, 0xB8)
GREEN = RGBColor(0x2E, 0x8B, 0x57)
AMBER = RGBColor(0xE8, 0x8A, 0x1A)
RED = RGBColor(0xC0, 0x39, 0x2B)
GREY = RGBColor(0x5A, 0x5A, 0x5A)
LIGHT = RGBColor(0xF2, 0xF5, 0xFA)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
DARK = RGBColor(0x22, 0x2B, 0x35)

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)

prs = Presentation()
prs.slide_width = SLIDE_W
prs.slide_height = SLIDE_H
BLANK = prs.slide_layouts[6]


# --------------------------------------------------------------------------- helpers
def _slide():
    return prs.slides.add_slide(BLANK)


def _rect(slide, x, y, w, h, color, line=None):
    shp = slide.shapes.add_shape(1, x, y, w, h)
    shp.fill.solid()
    shp.fill.fore_color.rgb = color
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(1)
    shp.shadow.inherit = False
    return shp


def _text(slide, x, y, w, h, runs, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
          wrap=True, space_after=4):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = anchor
    tf.margin_left = Pt(2)
    tf.margin_right = Pt(2)
    tf.margin_top = Pt(1)
    tf.margin_bottom = Pt(1)
    first = True
    for para in runs:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.alignment = align
        p.space_after = Pt(space_after)
        p.space_before = Pt(0)
        if isinstance(para, tuple):
            para = [para]
        for seg in para:
            text, size, bold, color = seg[0], seg[1], seg[2], seg[3]
            italic = seg[4] if len(seg) > 4 else False
            r = p.add_run()
            r.text = text
            r.font.size = Pt(size)
            r.font.bold = bold
            r.font.italic = italic
            r.font.color.rgb = color
            r.font.name = "Segoe UI"
    return tb


def _header(slide, title, kicker="DefectIQ AI Solution"):
    _rect(slide, 0, 0, SLIDE_W, Inches(1.15), NAVY)
    _rect(slide, 0, Inches(1.15), SLIDE_W, Pt(4), TEAL)
    _text(slide, Inches(0.6), Inches(0.12), Inches(12), Inches(0.35),
          [(kicker.upper(), 11, True, RGBColor(0x9E, 0xC4, 0xE8))])
    _text(slide, Inches(0.6), Inches(0.38), Inches(12.1), Inches(0.7),
          [(title, 27, True, WHITE)], anchor=MSO_ANCHOR.MIDDLE)
    _text(slide, Inches(0.6), Inches(7.08), Inches(9), Inches(0.3),
          [("NTT DATA  |  DefectIQ - Defect Management Agentic AI", 9, False, GREY)])


def _bullets(slide, x, y, w, h, items, size=15, gap=10, color=DARK):
    paras = []
    for it in items:
        if isinstance(it, tuple):
            txt, lvl = it
        else:
            txt, lvl = it, 0
        prefix = ("      " * lvl) + "•  "
        clr = color if lvl == 0 else GREY
        sz = size if lvl == 0 else size - 2
        paras.append([(prefix + txt, sz, False, clr)])
    _text(slide, x, y, w, h, paras, space_after=gap)


def _chip(slide, x, y, w, h, title, value, vcolor):
    _rect(slide, x, y, w, h, LIGHT)
    _rect(slide, x, y, w, Pt(5), vcolor)
    _text(slide, x, y + Inches(0.14), w, Inches(0.6),
          [(value, 26, True, vcolor)], align=PP_ALIGN.CENTER)
    _text(slide, x, y + Inches(0.78), w, Inches(0.4),
          [(title, 10.5, False, GREY)], align=PP_ALIGN.CENTER)


# =========================================================================== 1 title
s = _slide()
_rect(s, 0, 0, SLIDE_W, SLIDE_H, NAVY)
_rect(s, 0, Inches(4.55), SLIDE_W, Pt(5), TEAL)
_text(s, Inches(0.9), Inches(0.7), Inches(11), Inches(0.5),
      [("NTT DATA", 16, True, RGBColor(0x9E, 0xC4, 0xE8))])
_text(s, Inches(0.9), Inches(2.35), Inches(11.5), Inches(1.3),
      [("DefectIQ", 60, True, WHITE)])
_text(s, Inches(0.9), Inches(3.5), Inches(11.5), Inches(1.0),
      [("End-to-End Defect Management - Agentic AI Solution", 24, False,
        RGBColor(0xD6, 0xE4, 0xF4))])
_text(s, Inches(0.9), Inches(4.85), Inches(11.5), Inches(0.7),
      [("GitHub + Customer Smartsheet -> one dashboard, reconciled, with a grounded AI assistant.",
        15, False, RGBColor(0xC6, 0xD6, 0xEA))])
_text(s, Inches(0.9), Inches(6.5), Inches(11.5), Inches(0.5),
      [("Solution Demo", 13, True, TEAL)])

# =========================================================================== 2 problem -> solution
s = _slide()
_header(s, "The Problem & What DefectIQ Delivers")
_rect(s, Inches(0.6), Inches(1.5), Inches(6.0), Inches(4.9), WHITE, line=RGBColor(0xD0, 0xD8, 0xE2))
_rect(s, Inches(0.6), Inches(1.5), Inches(6.0), Inches(0.6), RED)
_text(s, Inches(0.6), Inches(1.56), Inches(6.0), Inches(0.5),
      [("The Problem", 16, True, WHITE)], align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
_bullets(s, Inches(0.85), Inches(2.35), Inches(5.5), Inches(3.9),
         [
             "Defects live in two systems: GitHub (engineering) and Smartsheet (customer).",
             "Pulling the data was a manual, repetitive export every time.",
             "Excel VLOOKUPs had to be refreshed by hand after each pull.",
             "No always-current consolidated view, and no easy way to ask questions of the data.",
         ], size=14, gap=14)
_rect(s, Inches(6.9), Inches(1.5), Inches(5.8), Inches(4.9), WHITE, line=RGBColor(0xD0, 0xD8, 0xE2))
_rect(s, Inches(6.9), Inches(1.5), Inches(5.8), Inches(0.6), GREEN)
_text(s, Inches(6.9), Inches(1.56), Inches(5.8), Inches(0.5),
      [("DefectIQ Delivers", 16, True, WHITE)], align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
_bullets(s, Inches(7.15), Inches(2.35), Inches(5.3), Inches(3.9),
         [
             "Python bot automates the data pull - no manual export.",
             "Same Excel workbook kept as-is: VLOOKUPs + macros preserved, backed up each run.",
             "Dashboard recomputes a reliable consolidated view in Python.",
             "KPIs, charts, filtering, CRUD and Excel exports.",
             "Agentic AI chatbot - plain-English answers, grounded on real data only.",
         ], size=13.5, gap=11)

# =========================================================================== 3 workflow
s = _slide()
_header(s, "The Service Workflow - One Command")
_text(s, Inches(0.6), Inches(1.35), Inches(12), Inches(0.4),
      [[("python main.py", 14, True, NAVY),
        ("  runs four services in sequence - all config in a single .env file.", 14, False, GREY)]])
boxes = [
    ("1  GitHub", ["Driver-free browser bot", "Login (pauses for MFA)", "Export issues -> CSV"], BLUE),
    ("2  Smartsheet", ["Fresh browser session", "Login (pauses for MFA)", "Export sheet -> Excel"], TEAL),
    ("3  Load + Reconcile", ["Load both exports", "Join on Action ID", "Consolidated status"], GREEN),
    ("4  Dashboard + AI", ["FastAPI web app", "KPIs, charts, CRUD", "Agentic AI assistant"], AMBER),
]
bx = Inches(0.6)
bw = Inches(2.92)
gap = Inches(0.18)
by = Inches(2.15)
bh = Inches(2.9)
for i, (title, items, color) in enumerate(boxes):
    x = Emu(int(bx) + i * (int(bw) + int(gap)))
    _rect(s, x, by, bw, bh, WHITE, line=RGBColor(0xD0, 0xD8, 0xE2))
    _rect(s, x, by, bw, Inches(0.62), color)
    _text(s, x, by + Inches(0.08), bw, Inches(0.5),
          [(title, 14, True, WHITE)], align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    _bullets(s, Emu(int(x) + int(Inches(0.18))), by + Inches(0.8),
             Emu(int(bw) - int(Inches(0.3))), Inches(1.9), items, size=12.5, gap=10)
    if i < 3:
        ax = Emu(int(x) + int(bw) + int(Inches(0.01)))
        _text(s, ax, by + Inches(1.1), Inches(0.18), Inches(0.5),
              [(">", 20, True, NAVY)], align=PP_ALIGN.CENTER)
_rect(s, Inches(0.6), Inches(5.4), Inches(12.1), Inches(1.25), LIGHT)
_text(s, Inches(0.85), Inches(5.55), Inches(11.6), Inches(1.0),
      [[("Built for a managed environment:  ", 12.5, True, NAVY),
        ("browser automation uses the Chrome DevTools Protocol (no chromedriver); logins pause so you "
         "complete MFA/SSO manually; every workbook write is backed up first.", 12.5, False, DARK)]])

# =========================================================================== 4 KPIs
s = _slide()
_header(s, "Live Snapshot - Consolidated KPIs")
_text(s, Inches(0.6), Inches(1.3), Inches(12), Inches(0.4),
      [("Real values the dashboard shows today (source last refreshed 11/16/2026).", 12, False, GREY)])
row1 = [("Issue Statuses", "682", NAVY), ("Open", "30", BLUE), ("In Progress", "57", AMBER),
        ("Closed", "593", GREEN), ("Unassigned", "353", RED)]
row2 = [("In Smartsheet", "781", TEAL), ("In GitHub", "682", BLUE), ("Matched", "4", GREEN),
        ("Missing in GitHub", "778", AMBER), ("Requires Review", "2", RED)]
cw = Inches(2.3)
cg = Inches(0.15)
cx0 = Inches(0.6)
for i, (t, v, c) in enumerate(row1):
    x = Emu(int(cx0) + i * (int(cw) + int(cg)))
    _chip(s, x, Inches(1.85), cw, Inches(1.4), t, v, c)
for i, (t, v, c) in enumerate(row2):
    x = Emu(int(cx0) + i * (int(cw) + int(cg)))
    _chip(s, x, Inches(3.5), cw, Inches(1.4), t, v, c)
_rect(s, Inches(0.6), Inches(5.3), Inches(12.1), Inches(1.15), LIGHT)
_text(s, Inches(0.85), Inches(5.45), Inches(11.6), Inches(0.9),
      [[("Talking point:  ", 13, True, NAVY),
        ("the large 'Missing in GitHub' and 'Unassigned' figures are exactly the reconciliation gaps the "
         "tool surfaces automatically.", 13, False, DARK)]])

# =========================================================================== 5 dashboard + chatbot
s = _slide()
_header(s, "Dashboard & Agentic AI Chatbot")
_rect(s, Inches(0.6), Inches(1.5), Inches(6.0), Inches(4.9), WHITE, line=RGBColor(0xD0, 0xD8, 0xE2))
_rect(s, Inches(0.6), Inches(1.5), Inches(6.0), Inches(0.6), BLUE)
_text(s, Inches(0.6), Inches(1.56), Inches(6.0), Inches(0.5),
      [("Dashboard", 16, True, WHITE)], align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
_bullets(s, Inches(0.85), Inches(2.35), Inches(5.5), Inches(3.9),
         [
             "KPI cards + interactive charts (status, priority, source, owner, module).",
             "Search, sort, filter the full defect table.",
             "Create / update / delete by role; edits survive a refresh.",
             "Excel exports and on-demand refresh.",
             "5 roles, per-endpoint permissions, full audit log.",
         ], size=13.5, gap=12)
_rect(s, Inches(6.9), Inches(1.5), Inches(5.8), Inches(4.9), WHITE, line=RGBColor(0xD0, 0xD8, 0xE2))
_rect(s, Inches(6.9), Inches(1.5), Inches(5.8), Inches(0.6), TEAL)
_text(s, Inches(6.9), Inches(1.56), Inches(5.8), Inches(0.5),
      [("Agentic AI Chatbot", 16, True, WHITE)], align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
_bullets(s, Inches(7.15), Inches(2.35), Inches(5.3), Inches(3.9),
         [
             "Ask defect questions in plain English; short, crisp answers.",
             "LLM plans and calls grounded tools, then writes the reply.",
             "Falls back to a deterministic offline mode with no LLM/network.",
             "Never answers from memory - every fact comes from real data.",
             "Uses exact counts - no invented IDs, statuses or owners.",
         ], size=13.5, gap=12)

# =========================================================================== 6 demo + close
s = _slide()
_header(s, "Live Demo Flow")
_bullets(s, Inches(0.6), Inches(1.5), Inches(12.1), Inches(3.6),
         [
             "Sign in as admin / admin123 and walk the KPI cards (682 Issue Statuses, 593 closed, 353 unassigned).",
             "Show the charts; filter the table (e.g. Open) and export the filtered set to Excel.",
             "Edit one defect, refresh to prove the edit survives, and show it in the audit log.",
             "Open the chatbot and run a few questions; finish as viewer / viewer123 to show role limits.",
         ], size=14.5, gap=14)
_rect(s, Inches(0.6), Inches(5.2), Inches(12.1), Inches(1.45), NAVY)
_text(s, Inches(0.85), Inches(5.4), Inches(11.6), Inches(1.1),
      [[("Run it:  ", 14, True, TEAL), ("python main.py", 14, False, WHITE),
        ("     Dashboard only:  ", 14, True, TEAL), ("python main.py --dashboard-only", 14, False, WHITE)],
       [("App:  ", 14, True, TEAL),
        ("http://127.0.0.1:8000   (admin / admin123)", 14, False, WHITE)]],
      space_after=8)

# --------------------------------------------------------------------------- save
out = Path(__file__).resolve().parent.parent / "DefectIQ_Demo.pptx"
prs.save(out)
print(f"Saved: {out}  ({len(prs.slides._sldIdLst)} slides)")
