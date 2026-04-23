"""
Generates the vertical DFIR-Report-style timeline PNG.

Layout (1200 px default width):

              ┌───────────────────┐
              │    Case Name      │   ← centred title box
              └───────────────────┘
                       │   1 px centre line
           ┌──────────┐             ← Day 1 marker
           │  Day 1   │
           └──────────┘
  ┌────────────────┐                ← LEFT event box
  │ 11:49 UTC      ├────────        ← connector → centre
  │ Initial Access │
  └────────────────┘
  │ Event Title (bold)              ← detail section
  ├─ comment level-1
  │  └─ comment level-2
                         ┌──────────────────┐ ← RIGHT event box
         ────────────────┤ 12:30 UTC Cred.  │
                         └──────────────────┘
                         │ Event Title (bold)
                         ├─ ...
"""

from __future__ import annotations

import io
import logging
import os
from datetime import datetime, timezone
from typing import NamedTuple, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

# ── Font paths ────────────────────────────────────────────────────────────────
# Override the font directory by setting the IRIS_FONT_DIR environment variable,
# e.g. for local development: export IRIS_FONT_DIR=/usr/share/fonts/truetype/dejavu
_LATO_DIR   = os.environ.get("IRIS_FONT_DIR", "/iriswebapp/app/static/assets/fonts/lato")
if not _LATO_DIR.endswith("/"):
    _LATO_DIR += "/"
_FONT_REG   = _LATO_DIR + "Lato-Regular.ttf"
_FONT_BOLD  = _LATO_DIR + "Lato-Bold.ttf"
_FONT_LIGHT = _LATO_DIR + "Lato-Light.ttf"
_FONT_BLACK = _LATO_DIR + "Lato-Black.ttf"

# ── Colours ───────────────────────────────────────────────────────────────────
C_BG          = (255, 255, 255)
C_TITLE_BG    = (174, 12,  12)       # default red; overridden by title_hex
C_TITLE_TEXT  = (255, 255, 255)

_log = logging.getLogger(__name__)
C_CENTER      = (155, 155, 155)      # main spine
C_CONNECTOR   = (175, 175, 175)      # horizontal box→centre connector
C_TREE        = (190, 190, 190)      # vertical stem + horizontal branches

C_DAY_BG      = (35,  35,  35)
C_DAY_TEXT    = (255, 255, 255)

C_BOX_BG      = (250, 250, 250)
C_BOX_BORDER  = (205, 205, 205)
C_BOX_SHADOW  = (225, 225, 225)      # 1-px shadow border (bottom+right)
C_BOX_TEXT    = (22,  22,  22)

C_EVTITLE     = (25,  25,  25)
C_COMMENT_L0  = (60,  60,  60)
C_COMMENT_L1  = (80,  80,  80)
C_COMMENT_L2  = (100, 100, 100)


# ── Data structures ───────────────────────────────────────────────────────────

class CommentItem(NamedTuple):
    level: int          # 0 = plain, 1 = "-", 2 = "--"
    text:  str


class DetailLine(NamedTuple):
    """A single rendered text line within the detail section."""
    text:         str
    bold:         bool
    level:        int         # 0/1/2 — drives indent + connector
    color:        Tuple[int, int, int]
    continuation: bool = False  # True = wrapped continuation; skip branch connector


class EventLayout(NamedTuple):
    side:             int              # +1 = right, -1 = left
    date_utc:         datetime
    category:         str
    box_lines:        List[str]        # wrapped header lines
    box_h:            int              # pixel height of the box
    detail_lines:     List[DetailLine]
    detail_h:         int              # pixel height of detail block
    box_header_lines: int = 1          # first N lines are time+cat; rest are event title
    box_border_color: Optional[Tuple[int, int, int]] = None  # None = use default
    box_border_w:     int = 1


class DayLayout(NamedTuple):
    label:    str                   # "Day N"
    height:   int


# ── UTC conversion ────────────────────────────────────────────────────────────

def _to_utc(dt: Optional[datetime], tz_str: Optional[str]) -> datetime:
    """Return *dt* as a naive UTC datetime.

    IRIS stores event_date already in UTC in the database; event_tz is metadata
    about the original input timezone and must NOT be re-applied.  We only need
    to strip any tzinfo that SQLAlchemy may have attached.
    """
    if dt is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ── Text helpers ──────────────────────────────────────────────────────────────

def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        _log.warning(
            "Font file not found: %s — falling back to default bitmap font. "
            "Set IRIS_FONT_DIR to a directory containing Lato .ttf files for "
            "best rendering quality.",
            path,
        )
        return ImageFont.load_default()


def _text_w(font: ImageFont.FreeTypeFont, text: str) -> int:
    bb = font.getbbox(text)
    return bb[2] - bb[0]


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_px: int) -> List[str]:
    """Wrap *text* so each line fits within *max_px* pixels.

    Falls back to character-level chunking for words that are themselves
    wider than *max_px* (e.g. long paths, hashes, URLs with no spaces).
    """
    if not text:
        return []

    def _chunk_word(word: str) -> List[str]:
        """Split a single word that is too wide to fit on one line."""
        chunks, cur = [], ""
        for ch in word:
            if _text_w(font, cur + ch) <= max_px:
                cur += ch
            else:
                if cur:
                    chunks.append(cur)
                cur = ch
        if cur:
            chunks.append(cur)
        return chunks or [word]

    words  = text.split()
    lines  = []
    cur    = ""
    for word in words:
        candidate = (cur + " " + word).strip()
        if _text_w(font, candidate) <= max_px:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            # If the bare word is too wide, chunk it character by character
            if _text_w(font, word) > max_px:
                chunks = _chunk_word(word)
                lines.extend(chunks[:-1])
                cur = chunks[-1]
            else:
                cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def _parse_comment(raw: str) -> List[CommentItem]:
    items: List[CommentItem] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("-- "):
            items.append(CommentItem(2, stripped[3:]))
        elif stripped.startswith("--"):
            items.append(CommentItem(2, stripped[2:].strip()))
        elif stripped.startswith("- "):
            items.append(CommentItem(1, stripped[2:]))
        elif stripped.startswith("-"):
            items.append(CommentItem(1, stripped[1:].strip()))
        else:
            items.append(CommentItem(1, stripped))
    return items


# ── Layout calculation ────────────────────────────────────────────────────────

def _measure_box(header: str, font: ImageFont.FreeTypeFont,
                 box_w: int, pad_h: int, pad_v: int,
                 line_h: int, min_h: int) -> Tuple[List[str], int]:
    lines = _wrap(header, font, box_w - 2 * pad_h)
    h = max(min_h, len(lines) * line_h + 2 * pad_v)
    return lines, h


def _build_detail_lines(event_title: str, comment_items: List[CommentItem],
                        fonts: dict, max_w: int,
                        indent_l0: int, indent_l1: int, indent_l2: int,
                        tree_h_len: int, tree_text_gap: int) -> List[DetailLine]:
    detail: List[DetailLine] = []

    def _avail(level: int, bold: bool) -> int:
        level_indent = indent_l0 if level == 0 else (indent_l1 if level == 1 else indent_l2)
        return max_w - (tree_h_len + tree_text_gap + level_indent)

    def _append_wrapped(text: str, bold: bool, level: int, color):
        font = fonts["cmt"]
        lines = _wrap(text, font, _avail(level, bold))
        for i, ln in enumerate(lines):
            detail.append(DetailLine(ln, bold, level, color, continuation=(i > 0)))

    if event_title:
        _append_wrapped(event_title, True, 1, C_EVTITLE)

    for ci in comment_items:
        # Since level 0 is eliminated, default everything non-L2 to L1 logic
        l = ci.level if ci.level > 0 else 1
        color = C_COMMENT_L1 if l == 1 else C_COMMENT_L2
        _append_wrapped(ci.text, False, l, color)

    return detail


# ── Main render entry point ───────────────────────────────────────────────────

def render(
    events_raw: list,
    case_name: str,
    title_hex: str = "#AE0C0C",
    earliest_date = None,
    title_in_box: bool = False,
    anon_map: dict = None,
    highlight_hex: str = None,
    cat_colors: dict = None,
) -> bytes:
    """
    Render a vertical DFIR-Report-style HDPI timeline PNG (2400px wide) and return it as bytes.

    *events_raw* must be CasesEvent objects with .event_date, .event_tz,
    .event_title, and .category (the relationship list).
    """
    if not events_raw:
        return _render_empty(case_name, 2400, title_hex)

    # ── Fonts ────────────────────────────────────────────────────────────────
    target_W = 2400
    M = 2  # Supersampling multiplier: render at 2x resolution
    W = target_W * M

    # Scale font sizes proportionally to image width (baseline: 1200 px -> scale at W)
    scale = W / 1200.0
    sz = lambda base: max(8, round(base * scale))

    fonts = {
        "title_bar": _load_font(_FONT_BLACK, sz(24)),
        "day":       _load_font(_FONT_BOLD,  sz(14)),
        "box":       _load_font(_FONT_BOLD,  sz(13)),
        "box_title": _load_font(_FONT_REG,   sz(13)),  # regular weight for title-in-box style
        "cmt":       _load_font(_FONT_REG,   sz(12)),  # use Regular instead of Light for legibility
    }

    # ── Layout constants (all in px, scaled) ─────────────────────────────────
    CX           = W // 2          # centre-line x
    TITLE_PAD_H  = sz(48)         # horizontal padding inside title box
    TITLE_PAD_V  = sz(16)         # vertical padding inside title box
    TITLE_CORNER = sz(8)
    TITLE_TOP    = sz(30)          # gap from image top to title box top
    TITLE_SHADOW = sz(3)           # shadow offset for title box
    CONTENT_TOP  = sz(20)          # gap below title box to first content
    BOTTOM_PAD   = sz(40)
    CENTER_W     = 2               # spine — most prominent

    DAY_BOX_W    = sz(130)
    DAY_BOX_H    = sz(40)
    DAY_CORNER   = sz(5)
    DAY_TOP_PAD  = sz(26)
    DAY_BOT_PAD  = sz(14)

    BOX_OFFSET   = sz(25)         # gap: centre line ↔ nearest box edge
    BOX_W        = sz(320)  # narrower fixed width
    BOX_CORNER   = sz(7)
    BOX_PAD_H    = sz(12)
    BOX_PAD_V    = sz(9)
    BOX_LINE_H   = sz(17)
    BOX_MIN_H    = sz(38)
    CONN_W       = 1              # connector — secondary

    DETAIL_GAP   = sz(10)         # gap: box bottom → first detail line
    CMT_LINE_H   = sz(15)         # line height for all detail text

    # Tree connector geometry (offsets from bx1 for right-side boxes,
    # measured from bx2 going left for left-side boxes)
    TREE_INDENT_L0 = sz(0)        # vertical stem x relative to detail_x
    TREE_INDENT_L1 = sz(12)       # extra indent for level-1 horizontals
    TREE_INDENT_L2 = sz(24)       # extra indent for level-2 horizontals
    TREE_H_LEN     = sz(8)        # horizontal stub length
    TREE_TEXT_G    = sz(12)       # gap after horizontal stub → text
    TREE_LINE_W    = 1            # tree lines — lightest

    # Detail text wraps within the box width for a clean, contained look
    DETAIL_MAX_W = BOX_W - BOX_PAD_H * 2

    EVENT_BOT    = sz(24)         # spacing below last detail line

    # ── Parse & sort events ───────────────────────────────────────────────────
    parsed = []
    for ev in events_raw:
        dt_utc = _to_utc(ev.event_date, ev.event_tz)
        cat    = ev.category[0].name if ev.category else "Unknown"
        parsed.append({
            "dt":        dt_utc,
            "cat":       cat,
            "title":     (ev.event_title or "").strip(),
            "comment":   "",     # filled below via attribute_setup helper
            "highlight": False,  # filled below
            "_ev":       ev,
        })

    # Attach comment, highlight flag and category override from custom attributes
    # (imported lazily to avoid circular import; attribute_setup is always in the same package)
    try:
        from iris_timelineexport_module.timeline_handler.attribute_setup import get_comment, get_override_category, get_highlight
        for p in parsed:
            p["comment"]   = get_comment(p["_ev"])
            p["highlight"] = get_highlight(p["_ev"])
            override = get_override_category(p["_ev"])
            if override:
                p["cat"] = override
    except Exception:
        _log.warning("Failed to load event comments from custom attributes", exc_info=True)

    # Apply anonymization substitutions
    if anon_map:
        try:
            from iris_timelineexport_module.timeline_handler.attribute_setup import apply_anon_map
        except Exception:
            _log.warning("Failed to import apply_anon_map — skipping anonymization", exc_info=True)
            anon_map = {}
    if anon_map:
        for p in parsed:
            p["title"]   = apply_anon_map(p["title"],   anon_map)
            p["cat"]     = apply_anon_map(p["cat"],     anon_map)
            p["comment"] = apply_anon_map(p["comment"], anon_map)

    parsed.sort(key=lambda x: x["dt"])

    # ── Day-number map ────────────────────────────────────────────────────────
    unique_days = sorted({p["dt"].date() for p in parsed})
    base_date = earliest_date if earliest_date else unique_days[0]
    day_num_map = {d: (d - base_date).days + 1 for d in unique_days}

    # ── Build layout sequence ─────────────────────────────────────────────────
    layout_seq = []          # list of (EventLayout | DayLayout)
    current_day = None
    side        = 1          # start with right

    for p in parsed:
        day = p["dt"].date()
        if day != current_day:
            current_day = day
            label = f"Day {day_num_map[day]}"
            layout_seq.append(DayLayout(label, DAY_BOX_H))

        header = f"{p['dt'].strftime('%H:%M')} UTC  {p['cat']}"
        if title_in_box and p["title"]:
            title_wrapped    = _wrap(p["title"], fonts["box_title"], BOX_W - 2 * BOX_PAD_H)
            box_lines        = [header] + title_wrapped
            box_h            = max(BOX_MIN_H, len(box_lines) * BOX_LINE_H + 2 * BOX_PAD_V)
            box_header_lines = 1
            detail_title     = ""
        else:
            box_lines, box_h = _measure_box(
                header, fonts["box"], BOX_W,
                BOX_PAD_H, BOX_PAD_V, BOX_LINE_H, BOX_MIN_H,
            )
            box_header_lines = len(box_lines)
            detail_title     = p["title"]

        comment_items = _parse_comment(p["comment"])
        detail_lines  = _build_detail_lines(
            detail_title, comment_items, fonts, DETAIL_MAX_W,
            TREE_INDENT_L0, TREE_INDENT_L1, TREE_INDENT_L2,
            TREE_H_LEN, TREE_TEXT_G,
        )

        # Calculate detail block height
        detail_h = 0
        if detail_lines:
            detail_h = DETAIL_GAP + len(detail_lines) * CMT_LINE_H

        # Resolve box border color: highlight > category color > default
        border_color: Optional[Tuple[int, int, int]] = None
        border_w = 1
        if p["highlight"] and highlight_hex:
            hc = _hex_to_rgb(highlight_hex)
            if hc:
                border_color = hc
                border_w = sz(3)   # ~6px at final 2400px after 2× downsample
        if border_color is None and cat_colors and p["cat"] in cat_colors:
            cc = _hex_to_rgb(cat_colors[p["cat"]])
            if cc:
                border_color = cc
                border_w = sz(2)   # ~4px at final 2400px after 2× downsample

        layout_seq.append(EventLayout(
            side             = side,
            date_utc         = p["dt"],
            category         = p["cat"],
            box_lines        = box_lines,
            box_h            = box_h,
            detail_lines     = detail_lines,
            detail_h         = detail_h,
            box_header_lines = box_header_lines,
            box_border_color = border_color,
            box_border_w     = border_w,
        ))
        side = -side

    # ── Measure title box ─────────────────────────────────────────────────────
    tf   = fonts["title_bar"]
    tbb  = tf.getbbox(case_name)
    tw   = tbb[2] - tbb[0]
    max_title_px = W - 2 * sz(120)   # max box width
    display_name = case_name
    while tw > max_title_px and len(display_name) > 4:
        display_name = display_name[:-2] + "…"
        tbb = tf.getbbox(display_name)
        tw  = tbb[2] - tbb[0]
    th = tbb[3] - tbb[1]

    title_box_w  = tw + TITLE_PAD_H * 2
    title_box_h  = th + TITLE_PAD_V * 2
    title_box_x1 = (W - title_box_w) // 2
    title_box_x2 = title_box_x1 + title_box_w
    title_box_y1 = TITLE_TOP
    title_box_y2 = title_box_y1 + title_box_h

    TITLE_SECTION_H = TITLE_TOP + title_box_h + TITLE_SHADOW  # space reserved for title

    # ── Calculate total image height ──────────────────────────────────────────
    y = TITLE_SECTION_H + CONTENT_TOP
    for item in layout_seq:
        if isinstance(item, DayLayout):
            y += DAY_TOP_PAD + DAY_BOX_H + DAY_BOT_PAD
        else:
            y += item.box_h + item.detail_h + EVENT_BOT
    total_h = y + BOTTOM_PAD

    # ── Create canvas ─────────────────────────────────────────────────────────
    img  = Image.new("RGB", (W, total_h), C_BG)
    draw = ImageDraw.Draw(img)

    # ── Title box ─────────────────────────────────────────────────────────────
    tc = _hex_to_rgb(title_hex)
    if tc is None:
        _log.warning("Invalid title_hex value %r — falling back to default red", title_hex)
        tc = C_TITLE_BG
    # Shadow: draw a slightly offset, slightly darker rounded rect first
    shadow_c = tuple(max(0, c - 40) for c in tc)
    draw.rounded_rectangle(
        [(title_box_x1 + TITLE_SHADOW, title_box_y1 + TITLE_SHADOW),
         (title_box_x2 + TITLE_SHADOW, title_box_y2 + TITLE_SHADOW)],
        radius=TITLE_CORNER, fill=shadow_c,
    )
    draw.rounded_rectangle(
        [(title_box_x1, title_box_y1), (title_box_x2, title_box_y2)],
        radius=TITLE_CORNER, fill=tc,
    )
    tx = (W - tw) // 2
    ty = title_box_y1 + TITLE_PAD_V - tbb[1]
    draw.text((tx, ty), display_name, font=tf, fill=C_TITLE_TEXT)

    # ── Centre line ───────────────────────────────────────────────────────────
    y_content_top = TITLE_SECTION_H + CONTENT_TOP
    draw.line(
        [(CX, title_box_y2 + TITLE_SHADOW), (CX, total_h - BOTTOM_PAD)],
        fill=C_CENTER, width=CENTER_W,
    )

    # ── Draw layout items ─────────────────────────────────────────────────────
    y_cur = y_content_top

    for item in layout_seq:

        if isinstance(item, DayLayout):
            y_cur += DAY_TOP_PAD
            dx1 = CX - DAY_BOX_W // 2
            dx2 = CX + DAY_BOX_W // 2
            draw.rounded_rectangle(
                [(dx1, y_cur), (dx2, y_cur + DAY_BOX_H)],
                radius=DAY_CORNER, fill=C_DAY_BG,
            )
            _draw_centered_text(draw, item.label, fonts["day"],
                                CX, y_cur, DAY_BOX_H, C_DAY_TEXT)
            y_cur += DAY_BOX_H + DAY_BOT_PAD
            continue

        # ── Event ─────────────────────────────────────────────────────────────
        s = item.side   # +1 right, -1 left

        if s == 1:      # right
            bx1 = CX + BOX_OFFSET
            bx2 = bx1 + BOX_W
            conn_x_box  = bx1
            conn_x_line = CX
            # detail tree stems from the left edge of the box
            detail_x = bx1 + sz(8)
        else:           # left
            bx2 = CX - BOX_OFFSET
            bx1 = bx2 - BOX_W
            conn_x_box  = bx2
            conn_x_line = CX
            # detail tree stems from the left edge of the box (same side)
            detail_x = bx1 + sz(8)

        by1 = y_cur
        by2 = y_cur + item.box_h
        box_mid_y = (by1 + by2) // 2

        # Connector line: box edge → centre line
        draw.line(
            [(conn_x_box, box_mid_y), (conn_x_line, box_mid_y)],
            fill=C_CONNECTOR, width=CONN_W,
        )

        # Box: draw a 1-px shadow by stacking two rounded rects
        draw.rounded_rectangle(
            [(bx1 + 2, by1 + 2), (bx2 + 2, by2 + 2)],
            radius=BOX_CORNER, fill=C_BOX_SHADOW,
        )
        box_outline = item.box_border_color if item.box_border_color is not None else C_BOX_BORDER
        draw.rounded_rectangle(
            [(bx1, by1), (bx2, by2)],
            radius=BOX_CORNER, fill=C_BOX_BG, outline=box_outline, width=item.box_border_w,
        )

        # Box header text
        ty_box = by1 + BOX_PAD_V
        compact_box = len(item.box_lines) > item.box_header_lines
        for i, ln in enumerate(item.box_lines):
            if i < item.box_header_lines:
                if i == 0 and compact_box:
                    # compact style: time bold, category regular on same line
                    split_idx = ln.find("UTC  ")
                    if split_idx >= 0:
                        time_part = ln[:split_idx + 5]
                        cat_part  = ln[split_idx + 5:]
                        draw.text((bx1 + BOX_PAD_H, ty_box), time_part,
                                  font=fonts["box"], fill=C_BOX_TEXT)
                        time_w = int(fonts["box"].getlength(time_part))
                        draw.text((bx1 + BOX_PAD_H + time_w, ty_box), cat_part,
                                  font=fonts["box_title"], fill=C_BOX_TEXT)
                    else:
                        draw.text((bx1 + BOX_PAD_H, ty_box), ln,
                                  font=fonts["box"], fill=C_BOX_TEXT)
                else:
                    draw.text((bx1 + BOX_PAD_H, ty_box), ln,
                              font=fonts["box"], fill=C_BOX_TEXT)
            else:
                draw.text((bx1 + BOX_PAD_H, ty_box), ln,
                          font=fonts["box_title"], fill=C_EVTITLE)
            ty_box += BOX_LINE_H

        y_cur += item.box_h

        # ── Detail section ─────────────────────────────────────────────────────
        if not item.detail_lines:
            y_cur += EVENT_BOT
            continue

        y_cur += DETAIL_GAP

        # vertical stem x: fixed reference point for all tree branches
        vtree_x = detail_x
        half = CMT_LINE_H // 2

        # 1. Main vertical stem: from bottom of the box down to the last L1/L2 item
        main_stem_bot = None
        current_y = y_cur
        has_l1 = False
        for dl in item.detail_lines:
            if dl.level == 1 and not dl.continuation:
                main_stem_bot = current_y + half
                has_l1 = True
            elif dl.level == 2 and not dl.continuation and not has_l1:
                main_stem_bot = current_y + half
            current_y += CMT_LINE_H
            
        if main_stem_bot is not None:
            draw.line(
                [(vtree_x, by2), (vtree_x, main_stem_bot)],
                fill=C_TREE, width=TREE_LINE_W,
            )

        # 2. Draw each detail line and branch
        last_l1_y = None
        for dl in item.detail_lines:
            lh         = CMT_LINE_H
            font       = fonts["cmt"]
            line_mid_y = y_cur + lh // 2

            if dl.level == 1 and not dl.continuation:
                h_start = vtree_x
                h_end   = vtree_x + TREE_INDENT_L1 + TREE_H_LEN
                draw.line([(h_start, line_mid_y), (h_end, line_mid_y)], fill=C_TREE, width=TREE_LINE_W)
                last_l1_y = line_mid_y
                
            elif dl.level == 2 and not dl.continuation:
                x_l2_stem = vtree_x + TREE_INDENT_L1
                if last_l1_y is not None:
                    # Drop vertical line from previous L1 down to this L2
                    draw.line([(x_l2_stem, last_l1_y), (x_l2_stem, line_mid_y)], fill=C_TREE, width=TREE_LINE_W)
                    last_l1_y = line_mid_y  # Update so subsequent L2s continue from here
                else:
                    # Unlikely, but if L2 appears before any L1, connect horizontally from main stem
                    draw.line([(vtree_x, line_mid_y), (x_l2_stem, line_mid_y)], fill=C_TREE, width=TREE_LINE_W)
                    last_l1_y = line_mid_y
                    
                h_start = x_l2_stem
                h_end   = vtree_x + TREE_INDENT_L2 + TREE_H_LEN
                draw.line([(h_start, line_mid_y), (h_end, line_mid_y)], fill=C_TREE, width=TREE_LINE_W)

            # Determine text X position based on level
            if dl.level <= 1:
                text_x = vtree_x + TREE_INDENT_L1 + TREE_H_LEN + TREE_TEXT_G
            elif dl.level == 2:
                text_x = vtree_x + TREE_INDENT_L2 + TREE_H_LEN + TREE_TEXT_G

            draw.text((text_x, y_cur), dl.text, font=font, fill=dl.color)
            y_cur += lh

        y_cur += EVENT_BOT

    # ── Encode to PNG bytes ───────────────────────────────────────────────────
    if M > 1:
        resample_filter = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        img = img.resize((target_W, total_h // M), resample=resample_filter)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True, dpi=(300, 300))
    return buf.getvalue()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hex_to_rgb(hex_str: str) -> Optional[Tuple[int, int, int]]:
    h = hex_str.lstrip("#")
    if len(h) == 6:
        try:
            return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
    return None


def _draw_centered_text(draw, text: str, font, cx: int, y_top: int,
                        box_h: int, color) -> None:
    bb = font.getbbox(text)
    tw = bb[2] - bb[0]
    th = bb[3] - bb[1]
    draw.text(
        (cx - tw // 2, y_top + (box_h - th) // 2 - bb[1]),
        text, font=font, fill=color,
    )


def _render_empty(case_name: str, img_width: int, title_hex: str) -> bytes:
    """Return a minimal PNG saying there are no marked events."""
    W, H = img_width, 200
    img  = Image.new("RGB", (W, H), C_BG)
    draw = ImageDraw.Draw(img)
    tc   = _hex_to_rgb(title_hex) or C_TITLE_BG
    draw.rectangle([(0, 0), (W, 72)], fill=tc)
    font_t = _load_font(_FONT_BLACK, 22)
    font_m = _load_font(_FONT_LIGHT, 14)
    _draw_centered_text(draw, case_name, font_t, W // 2, 0, 72, (255, 255, 255))
    msg = "No events marked for export (set 'Include in Export' in the Timeline Export custom attribute)."
    draw.text((30, 100), msg, font=font_m, fill=(80, 80, 80))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
