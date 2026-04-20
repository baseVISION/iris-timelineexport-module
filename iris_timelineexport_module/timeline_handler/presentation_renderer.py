"""
Generates horizontal 16:9 PNGs for PowerPoint presentations.
Chunks events into multiple slides (e.g. 5 per slide).
Uses an alternating top/bottom layout.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import List, Tuple

from PIL import Image, ImageDraw, ImageFont

# ── Font paths ────────────────────────────────────────────────────────────────
_FONT_DIR  = "/usr/share/fonts/truetype/dejavu/"
_FONT_REG  = _FONT_DIR + "DejaVuSans.ttf"
_FONT_BOLD = _FONT_DIR + "DejaVuSans-Bold.ttf"

# ── Colours ───────────────────────────────────────────────────────────────────
C_BG_TRANS    = (255, 255, 255, 0)   # Transparent background
C_CENTER_LINE = (120, 120, 120, 255)
C_NODE        = (174, 12, 12, 255)   # Default red, overridden by config
C_NODE_BORDER = (255, 255, 255, 255)

C_BOX_BG      = (250, 250, 250, 240) # Slightly transparent modern boxes
C_BOX_BORDER  = (200, 200, 200, 255)
C_BOX_TEXT    = (20, 20, 20, 255)
C_BOX_TITLE   = (0, 0, 0, 255)
C_COMMENT     = (60, 60, 60, 255)


C_DAY_BG      = (35,  35,  35, 255)
C_DAY_TEXT    = (255, 255, 255, 255)

def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()

def _hex_to_rgba(hex_str: str, alpha: int = 255) -> Tuple[int, int, int, int]:
    h = hex_str.lstrip("#")
    if len(h) != 6:
        return (174, 12, 12, alpha)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)
    except ValueError:
        return (174, 12, 12, alpha)

def _wrap(text: str, font: ImageFont.FreeTypeFont, max_px: int) -> List[str]:
    if not text:
        return []
    words = text.split()
    lines = []
    cur = ""
    for word in words:
        candidate = (cur + " " + word).strip()
        bb = font.getbbox(candidate)
        w = bb[2] - bb[0]
        if w <= max_px:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]

def render_presentation(
    events_raw: list, 
    case_name: str, 
    title_hex: str = "#AE0C0C", 
    events_per_slide: int = 5
) -> List[Tuple[bytes, int]]:
    """
    Renders 16:9 transparent PNGs. Returns a list of tuples: (png_bytes, slide_number).
    """
    if not events_raw:
        return []

    # 4K Default Resolution (16:9 HDPI)
    W, H = 3840, 2160
    CY = H // 2

    # Fonts - sized for reading at 4k without blur when downscaled
    f_date  = _load_font(_FONT_BOLD, 40)
    f_title = _load_font(_FONT_REG, 44)
    f_com   = _load_font(_FONT_REG, 44)
    f_day   = _load_font(_FONT_BOLD, 40)
    
    node_color = _hex_to_rgba(title_hex)

    # Parse and sort events
    parsed = []
    from iris_timelineexport_module.timeline_handler.attribute_setup import get_comment
    from iris_timelineexport_module.timeline_handler.png_renderer import _to_utc
    for ev in events_raw:
        dt = _to_utc(ev.event_date, ev.event_tz)
        cat = ev.category[0].name if ev.category else "Unknown"
        title = (ev.event_title or "").strip()
        try:
            comment = get_comment(ev)
        except Exception:
            comment = ""
        parsed.append({"dt": dt, "cat": cat, "title": title, "comment": comment, "_ev": ev})
    parsed.sort(key=lambda x: x["dt"])

    # Map dates to day numbers based on the earliest event
    unique_days = sorted({p["dt"].date() for p in parsed})
    day_num_map = {d: (d - unique_days[0]).days + 1 for d in unique_days}

    # Chunk events
    chunks = [parsed[i:i + events_per_slide] for i in range(0, len(parsed), events_per_slide)]
    slides = []

    for slide_idx, chunk in enumerate(chunks, start=1):
        img = Image.new("RGBA", (W, H), C_BG_TRANS)
        draw = ImageDraw.Draw(img)

        # Draw Center Line
        draw.line([(100, CY), (W - 100, CY)], fill=C_CENTER_LINE, width=12)

        # Group events in this chunk by day
        day_events = {}
        for ev in chunk:
            day = ev["dt"].date()
            if day not in day_events:
                day_events[day] = []
            day_events[day].append(ev)

        # We will split the timeline into total segments based on day transitions
        total_events = len(chunk)
        num_day_transitions = len(day_events)

        segment_width = W // (events_per_slide + num_day_transitions + 1)
        
        BOX_W = min(1000, (segment_width * 2) - 80)
        BOX_PAD = 40
        MAX_TEXT_W = BOX_W - (BOX_PAD * 2) - 20  # extra 20px margin for font measurement inaccuracies
        
        pos_idx = 1
        is_top = True # Start with top for each slide

        for day in sorted(day_events.keys()):
            # Draw day separator
            day_label = f"Day {day_num_map[day]}"
            x = segment_width * pos_idx

            # Day Separator Node / Box
            DAY_BOX_W = 240
            DAY_BOX_H = 80
            dx1 = x - DAY_BOX_W // 2
            dx2 = x + DAY_BOX_W // 2
            dy1 = CY - DAY_BOX_H // 2
            dy2 = CY + DAY_BOX_H // 2
            
            draw.rounded_rectangle([(dx1, dy1), (dx2, dy2)], radius=40, fill=C_DAY_BG)
            
            bb = f_day.getbbox(day_label)
            tw = bb[2] - bb[0]
            th = bb[3] - bb[1]
            draw.text((x - tw // 2, CY - th // 2 - bb[1] - 1), day_label, font=f_day, fill=C_DAY_TEXT)

            pos_idx += 1
            
            # Reset top/bottom alternation for new day
            is_top = True
            
            for ev_data in day_events[day]:
                x = segment_width * pos_idx

                # ── Build text content ─────────────────────────────────────────
                from iris_timelineexport_module.timeline_handler.png_renderer import _parse_comment
                
                time_str = ev_data["dt"].strftime("%H:%M UTC")
                lines: list = [
                    (f"{time_str} - {ev_data['cat']}", f_date, C_BOX_TITLE),
                    ("", f_title, C_BOX_TEXT),   # spacer
                ]
                for title_line in _wrap("- " + ev_data["title"], f_title, MAX_TEXT_W):
                    lines.append((title_line, f_title, C_BOX_TITLE))

                sub_lines: list = []
                for ci in _parse_comment(ev_data["comment"]):
                    if ci.level <= 1:
                        # First level comments are treated exactly like the event title in the main box
                          prefix = "- " if ci.level == 1 else ""
                          for wl in _wrap(prefix + ci.text, f_title, MAX_TEXT_W):
                            if wl:
                                lines.append((wl, f_title, C_BOX_TITLE))
                    else:
                        # Sub-items drop into the sub-box as bulleted lists
                        indent = 0 if ci.level == 2 else 40
                        prefix = "- " if ci.level == 2 else "-- "
                        wrapped = _wrap(prefix + ci.text, f_com, (MAX_TEXT_W - 20) - indent)
                        for wl in wrapped:
                            if wl:
                                sub_lines.append((wl, f_com, C_COMMENT, indent))

                # ── Box heights ────────────────────────────────────────────────
                box_h = BOX_PAD * 2
                for text, font, color in lines:
                    if text == "":
                        box_h += 20
                        continue
                    bb = font.getbbox(text)
                    box_h += (bb[3] - bb[1]) + 16

                sub_box_h = 0
                if sub_lines:
                    sub_box_h = (BOX_PAD // 2) * 2
                    for text, font, color, indent in sub_lines:
                        bb = font.getbbox(text)
                        sub_box_h += (bb[3] - bb[1]) + 16

                # ── Vertical placement ─────────────────────────────────────────
                # Main box is placed MARGIN px from the centre line.
                # Sub-box always extends further AWAY from centre (never toward it).
                MARGIN = 120

                if is_top:
                    by2 = CY - MARGIN          # bottom of main box
                    by1 = by2 - box_h          # top of main box
                    if sub_lines:
                        sby2 = by1 - 20        # sub-box sits above main box
                        sby1 = sby2 - sub_box_h
                    conn_edge = by2
                else:
                    by1 = CY + MARGIN          # top of main box
                    by2 = by1 + box_h          # bottom of main box
                    if sub_lines:
                        sby1 = by2 + 20        # sub-box sits below main box
                        sby2 = sby1 + sub_box_h
                    conn_edge = by1

                # ── Draw connector (centre line → main box) ────────────────────
                draw.line([(x, CY), (x, conn_edge)], fill=C_CENTER_LINE, width=8)

                # ── Draw node (on top of connector) ───────────────────────────
                r_outer, r_inner = 28, 20
                draw.ellipse([(x - r_outer, CY - r_outer), (x + r_outer, CY + r_outer)], fill=C_NODE_BORDER)
                draw.ellipse([(x - r_inner, CY - r_inner), (x + r_inner, CY + r_inner)], fill=node_color)

                # ── Draw main box ──────────────────────────────────────────────
                bx1 = x - (BOX_W // 2)
                bx2 = x + (BOX_W // 2)
                draw.rounded_rectangle([(bx1, by1), (bx2, by2)], radius=24,
                                        fill=C_BOX_BG, outline=C_BOX_BORDER, width=6)

                # ── Draw main text ─────────────────────────────────────────────
                ty = by1 + BOX_PAD
                for text, font, color in lines:
                    if text == "":
                        ty += 20
                        continue
                    bb = font.getbbox(text)
                    fh = bb[3] - bb[1]
                    draw.text((bx1 + BOX_PAD, ty), text, font=font, fill=color)
                    ty += fh + 16

                # ── Draw sub-box (comment) — always on outer side ──────────────
                if sub_lines:
                    sbx1 = bx1 + 10
                    sbx2 = bx2 - 20
                    stem_x = bx1 + 30

                    # Vertical connector from main box edge to sub-box edge
                    if is_top:
                        draw.line([(stem_x, by1), (stem_x, sby2)], fill=C_CENTER_LINE, width=4)
                    else:
                        draw.line([(stem_x, by2), (stem_x, sby1)], fill=C_CENTER_LINE, width=4)

                    draw.rounded_rectangle([(sbx1, sby1), (sbx2, sby2)], radius=16,
                                            fill=(240, 240, 240, 255), outline=(180, 180, 180, 255), width=4)

                    sty = sby1 + (BOX_PAD // 2)
                    for text, font, color, indent in sub_lines:
                        bb = font.getbbox(text)
                        fh = bb[3] - bb[1]
                        draw.text((sbx1 + (BOX_PAD // 2) + indent, sty), text, font=font, fill=color)
                        sty += fh + 16

                pos_idx += 1
                is_top = not is_top

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        slides.append((buf.getvalue(), slide_idx))

    return slides