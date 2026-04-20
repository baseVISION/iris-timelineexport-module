"""Re-generate presentation slides for cases 11 and 13 using the fixed renderer."""
import sys
sys.path.insert(0, "/iriswebapp")
from app import app, db
from app.models.cases import Cases, CasesEvent
import datetime, uuid, os, hashlib

with app.app_context():
    from iris_timelineexport_module.timeline_handler.attribute_setup import is_included
    from iris_timelineexport_module.timeline_handler.presentation_renderer import render_presentation
    from app.models import DataStoreFile
    from app.models.authorization import User
    from app.datamgmt.datastore.datastore_db import datastore_get_root, datastore_get_standard_path

    user = User.query.filter_by(active=True).order_by(User.id).first()

    for cid in (11, 13):
        # Remove old presentation slides
        old = DataStoreFile.query.filter(
            DataStoreFile.file_case_id == cid,
            DataStoreFile.file_original_name.like("timeline_presentation_%")
        ).all()
        for f in old:
            try:
                os.remove(f.file_local_name)
            except Exception:
                pass
            db.session.delete(f)
        db.session.commit()
        print(f"  [case {cid}] Removed {len(old)} old slide(s)")

        events = CasesEvent.query.filter(CasesEvent.case_id == cid).order_by(CasesEvent.event_date).all()
        marked = [e for e in events if is_included(e)]
        case_obj = Cases.query.get(cid)
        case_name = case_obj.name.split(" - ", 1)[-1] if case_obj else f"Case {cid}"

        slides = render_presentation(marked, case_name, title_hex="#AE0C0C", events_per_slide=5)
        print(f"  [case {cid}] Rendered {len(slides)} slide(s)")

        ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        root = datastore_get_root(cid)
        for png_bytes, slide_num in slides:
            fname = f"timeline_presentation_{ts}_slide_{slide_num}.png"
            dsf = DataStoreFile()
            dsf.file_original_name = fname
            dsf.file_description   = f"Timeline presentation slide {slide_num}"
            dsf.file_tags          = "timeline,export"
            dsf.file_password      = ""
            dsf.file_is_ioc        = False
            dsf.file_is_evidence   = False
            dsf.file_case_id       = cid
            dsf.file_date_added    = datetime.datetime.utcnow()
            dsf.added_by_user_id   = user.id
            dsf.file_local_name    = "tmp"
            dsf.file_parent_id     = root.path_id
            dsf.file_sha256        = hashlib.sha256(png_bytes).hexdigest()
            db.session.add(dsf)
            db.session.flush()

            local_path = datastore_get_standard_path(dsf, cid)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            with open(str(local_path), "wb") as fh:
                fh.write(png_bytes)
            dsf.file_local_name = str(local_path)
            db.session.flush()
            print(f"  [case {cid}] Slide {slide_num} saved → file_id={dsf.file_id}")

        db.session.commit()
