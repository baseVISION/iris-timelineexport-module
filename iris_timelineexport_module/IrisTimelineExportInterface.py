"""
IRIS module interface for Timeline Export.

Registers an on_manual_trigger_case hook ("Export Timeline Diagram") that:
  1. Queries all CasesEvent objects for the case.
  2. Filters those marked via the 'Include in Export' custom attribute.
  3. Renders a vertical DFIR-Report-style PNG with png_renderer.
  4. Saves the PNG to the case Datastore.
  5. Logs a direct download link.
"""

from __future__ import annotations

import datetime
import hashlib
import re
from typing import Any

from iris_interface.IrisModuleInterface import IrisModuleInterface, IrisModuleTypes
from iris_interface import IrisInterfaceStatus

import iris_timelineexport_module.IrisTimelineExportConfig as conf
from iris_timelineexport_module.timeline_handler.attribute_setup import (
    ensure_attribute_exists,
    ensure_case_attribute_exists,
    is_included,
    get_anon_map_raw,
    parse_anon_map,
    parse_cat_colors,
    apply_anon_map,
)
from iris_timelineexport_module.timeline_handler.png_renderer import render
from iris_timelineexport_module.timeline_handler.presentation_renderer import render_presentation


class IrisTimelineExportInterface(IrisModuleInterface):

    _module_name          = conf.module_name
    _module_description   = conf.module_description
    _interface_version    = conf.interface_version
    _module_version       = conf.module_version
    _module_type          = IrisModuleTypes.module_processor
    _pipeline_support     = conf.pipeline_support
    _pipeline_info        = conf.pipeline_info
    _module_configuration = conf.module_configuration

    # ── Registration ──────────────────────────────────────────────────────────

    def register_hooks(self, module_id: int) -> None:
        self.module_id = module_id

        # Ensure the custom attribute tabs exist on events and cases
        ensure_attribute_exists(self.log)
        ensure_case_attribute_exists(self.log)

        # Register the manual trigger on the case
        self.register_to_hook(
            module_id,
            iris_hook_name="on_manual_trigger_case",
            manual_hook_name="Export Timeline Diagram",
        )
        self.register_to_hook(
            module_id,
            iris_hook_name="on_manual_trigger_case",
            manual_hook_name="Export Timeline (PPTX-ready 16:9)",
        )
        self.register_to_hook(
            module_id,
            iris_hook_name="on_manual_trigger_case",
            manual_hook_name="Export Timeline Diagram (Anonymized)",
        )
        self.register_to_hook(
            module_id,
            iris_hook_name="on_manual_trigger_case",
            manual_hook_name="Export Timeline (PPTX-ready 16:9, Anonymized)",
        )
        self.log.info("IrisTimelineExport: hooks registered")

    # ── Hook dispatcher ───────────────────────────────────────────────────────

    def hooks_handler(
        self,
        hook_name: str,
        hook_ui_name: str,
        data: Any,
    ) -> IrisInterfaceStatus:

        self.log.info("IrisTimelineExport hook: %s (UI name: %s)", hook_name, hook_ui_name)

        if hook_name == "on_manual_trigger_case":
            if hook_ui_name == "Export Timeline (PPTX-ready 16:9)":
                return self._handle_export_presentation(data)
            elif hook_ui_name == "Export Timeline Diagram (Anonymized)":
                return self._handle_export(data, anonymized=True)
            elif hook_ui_name == "Export Timeline (PPTX-ready 16:9, Anonymized)":
                return self._handle_export_presentation(data, anonymized=True)
            else:
                return self._handle_export(data)

        self.log.warning("Unhandled hook: %s", hook_name)
        return IrisInterfaceStatus.I2Success(data=data, logs=list(self.message_queue))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _extract_case_obj(self, data: Any):
        """
        Extract the Cases ORM object from the hook payload.

        Returns the object on success, or raises ValueError with a descriptive
        message if the payload is malformed.
        """
        cases_obj = data[0] if isinstance(data, list) else data
        if cases_obj is None:
            raise ValueError("Hook payload is None")
        if not hasattr(cases_obj, "case_id"):
            raise ValueError(
                f"Hook payload has unexpected type {type(cases_obj).__name__!r}; "
                "expected a Cases object with a 'case_id' attribute"
            )
        return cases_obj

    # ── Export logic ──────────────────────────────────────────────────────────

    def _handle_export(self, data: Any, anonymized: bool = False) -> IrisInterfaceStatus:
        try:
            cases_obj = self._extract_case_obj(data)
        except ValueError as exc:
            msg = f"Invalid hook payload: {exc}"
            self.log.error(msg)
            return IrisInterfaceStatus.I2Error(
                data=data, logs=list(self.message_queue), message=msg,
            )
        case_id   = cases_obj.case_id
        raw_name  = cases_obj.name or f"Case {case_id}"
        case_name = re.sub(r"^#\d+\s*[-–]\s*", "", raw_name).strip()

        self.log.info("Exporting timeline for case %s: %s (anonymized=%s)", case_id, case_name, anonymized)

        # ── Load module config ────────────────────────────────────────────────
        status = self.get_configuration_dict()
        cfg    = status.get_data() if status.is_success() else {}
        title_color     = str(cfg.get("timeline_title_color",     "#AE0C0C"))
        highlight_color = str(cfg.get("timeline_highlight_color", "#FF8C00"))

        # ── Load anonymization map if requested ────────────────────────────────────
        anon_map = {}
        if anonymized:
            raw_map = get_anon_map_raw(cases_obj)
            anon_map = parse_anon_map(raw_map)
            self.log.info("Anonymization map has %d entries", len(anon_map))

        # ── Apply anonymization to case name ─────────────────────────────────────
        display_case_name = apply_anon_map(case_name, anon_map) if anon_map else case_name
        file_suffix = "_anon" if anonymized else ""

        # ── Load category color map ──────────────────────────────────────────────
        cat_colors = parse_cat_colors(str(cfg.get("timeline_category_colors", "")))
        self.log.info("Category color map has %d entries", len(cat_colors))

        # ── Query events ──────────────────────────────────────────────────────
        try:
            from app.models.cases import CasesEvent
            all_events = (
                CasesEvent.query
                .filter(CasesEvent.case_id == case_id)
                .order_by(CasesEvent.event_date)
                .all()
            )
        except Exception as exc:
            msg = f"Failed to query events for case {case_id}: {exc}"
            self.log.error(msg, exc_info=True)
            return IrisInterfaceStatus.I2Error(
                data=data, logs=list(self.message_queue), message=msg,
            )

        marked = [ev for ev in all_events if is_included(ev)]
        self.log.info("%d of %d events marked for export", len(marked), len(all_events))

        # ── Render PNGs ────────────────────────────────────────────────────────
        download_urls = []
        try:
            # 1. Generate full complete timeline
            png_bytes = render(marked, display_case_name, title_hex=title_color, title_in_box=True, anon_map=anon_map, highlight_hex=highlight_color, cat_colors=cat_colors)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
            filename = f"{ts}_timeline{file_suffix}.png"
            file_id = self._save_to_datastore(png_bytes, filename, case_id)
            if file_id:
                download_urls.append(f"/datastore/file/view/{file_id}?cid={case_id}")

            # 2. Generate per-day timeline pieces
            if marked:
                from iris_timelineexport_module.timeline_handler.png_renderer import _to_utc
                # Group by day
                day_groups = {}
                for ev in marked:
                    day = _to_utc(ev.event_date, ev.event_tz).date()
                    if day not in day_groups:
                        day_groups[day] = []
                    day_groups[day].append(ev)
                
                earliest = min(day_groups.keys())
                day_num_map = {d: (d - earliest).days + 1 for d in sorted(day_groups.keys())}
                
                # Render each day
                for day, day_events in day_groups.items():
                    day_idx = day_num_map[day]
                    try:
                        day_bytes = render(day_events, f"{display_case_name} - Day {day_idx}", title_hex=title_color, earliest_date=earliest, title_in_box=True, anon_map=anon_map, highlight_hex=highlight_color, cat_colors=cat_colors)
                        day_filename = f"{ts}_timeline_day{day_idx}{file_suffix}.png"
                        d_id = self._save_to_datastore(day_bytes, day_filename, case_id)
                        if d_id:
                            download_urls.append(f"/datastore/file/view/{d_id}?cid={case_id}")
                    except Exception as e:
                        self.log.error("Failed to render day %d: %s", day_idx, e)

        except Exception as exc:
            msg = f"Failed to render timeline PNG: {exc}"
            self.log.error(msg, exc_info=True)
            return IrisInterfaceStatus.I2Error(
                data=data, logs=list(self.message_queue), message=msg,
            )

        if not download_urls:
            msg = "Could not save PNGs to Datastore."
            self.log.error(msg)
            self.message_queue.append(msg)
            return IrisInterfaceStatus.I2Error(
                data=data, logs=list(self.message_queue), message=msg,
            )

        summary = (
            f"Timeline diagram exported ({len(marked)} events). "
            f"Downloads: {', '.join(download_urls)}"
        )
        self.message_queue.append(summary)

        return IrisInterfaceStatus.I2Success(
            data=data, logs=list(self.message_queue),
        )

    def _handle_export_presentation(self, data: Any, anonymized: bool = False) -> IrisInterfaceStatus:
        try:
            cases_obj = self._extract_case_obj(data)
        except ValueError as exc:
            msg = f"Invalid hook payload: {exc}"
            self.log.error(msg)
            return IrisInterfaceStatus.I2Error(
                data=data, logs=list(self.message_queue), message=msg,
            )
        case_id   = cases_obj.case_id
        raw_name  = cases_obj.name or f"Case {case_id}"
        case_name = re.sub(r"^#\d+\s*[-–]\s*", "", raw_name).strip()

        self.log.info("Exporting presentation timeline for case %s: %s (anonymized=%s)", case_id, case_name, anonymized)

        status = self.get_configuration_dict()
        cfg    = status.get_data() if status.is_success() else {}
        title_color     = str(cfg.get("timeline_title_color",     "#AE0C0C"))
        highlight_color = str(cfg.get("timeline_highlight_color", "#FF8C00"))

        anon_map = {}
        if anonymized:
            raw_map = get_anon_map_raw(cases_obj)
            anon_map = parse_anon_map(raw_map)
            self.log.info("Anonymization map has %d entries", len(anon_map))

        display_case_name = apply_anon_map(case_name, anon_map) if anon_map else case_name
        file_suffix = "_anon" if anonymized else ""

        cat_colors = parse_cat_colors(str(cfg.get("timeline_category_colors", "")))
        self.log.info("Category color map has %d entries", len(cat_colors))

        try:
            from app.models.cases import CasesEvent
            all_events = (
                CasesEvent.query
                .filter(CasesEvent.case_id == case_id)
                .order_by(CasesEvent.event_date)
                .all()
            )
        except Exception as exc:
            msg = f"Failed to query events for case {case_id}: {exc}"
            self.log.error(msg, exc_info=True)
            return IrisInterfaceStatus.I2Error(
                data=data, logs=list(self.message_queue), message=msg,
            )

        marked = [ev for ev in all_events if is_included(ev)]
        self.log.info("%d of %d events marked for presentation export", len(marked), len(all_events))

        try:
            slides = render_presentation(marked, display_case_name, title_hex=title_color, events_per_slide=5, anon_map=anon_map, highlight_hex=highlight_color, cat_colors=cat_colors)
        except Exception as exc:
            msg = f"Failed to render presentation PNGs: {exc}"
            self.log.error(msg, exc_info=True)
            return IrisInterfaceStatus.I2Error(
                data=data, logs=list(self.message_queue), message=msg,
            )

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        download_urls = []
        for png_bytes, slide_num in slides:
            filename = f"{ts}_timeline_presentation_slide{slide_num}{file_suffix}.png"
            file_id = self._save_to_datastore(png_bytes, filename, case_id)
            if file_id:
                download_urls.append(f"/datastore/file/view/{file_id}?cid={case_id}")

        if not download_urls:
            msg = "Could not save presentation PNGs to Datastore."
            self.log.error(msg)
            self.message_queue.append(msg)
            return IrisInterfaceStatus.I2Error(
                data=data, logs=list(self.message_queue), message=msg,
            )

        summary = (
            f"Presentation timeline exported ({len(slides)} slides). "
            f"Downloads: {', '.join(download_urls)}"
        )
        self.message_queue.append(summary)

        return IrisInterfaceStatus.I2Success(
            data=data, logs=list(self.message_queue),
        )

    # ── Datastore persistence ─────────────────────────────────────────────────

    def _save_to_datastore(
        self,
        png_bytes: bytes,
        filename: str,
        case_id: int,
    ) -> int | None:
        """
        Write *png_bytes* to the IRIS Datastore for *case_id*.
        Returns the DataStoreFile.file_id, or None on failure.

        Atomic pattern: write file to disk first, then commit the DB record.
        On any error the DB session is rolled back and any partial file removed.
        """
        try:
            from app import db
            from app.models import DataStoreFile
            from app.models.authorization import User
            from app.datamgmt.datastore.datastore_db import (
                datastore_get_root,
                datastore_get_standard_path,
            )

            first_user = (
                User.query
                .filter_by(active=True)
                .order_by(User.id)
                .first()
            )
            if first_user is None:
                self.log.error(
                    "No active user found in the database; cannot save file "
                    "with valid ownership for case %s", case_id
                )
                return None
            user_id = first_user.id

            root = datastore_get_root(case_id)
            if root is None:
                self.log.error("Could not get Datastore root for case %s", case_id)
                return None

            folder_id = self._get_or_create_folder(db, case_id, root.path_id)

            sha256 = hashlib.sha256(png_bytes).hexdigest()

            dsf = DataStoreFile()
            dsf.file_original_name = filename
            dsf.file_description   = "Timeline Export Diagram"
            dsf.file_tags          = "timeline,export"
            dsf.file_password      = ""
            dsf.file_is_ioc        = False
            dsf.file_is_evidence   = False
            dsf.file_case_id       = case_id
            dsf.file_date_added    = datetime.datetime.now(datetime.timezone.utc)
            dsf.added_by_user_id   = user_id
            dsf.file_local_name    = "tmp"
            dsf.file_parent_id     = folder_id
            dsf.file_sha256        = sha256
            dsf.file_size          = len(png_bytes)

            # --- atomic section: write file first, then commit DB ---
            db.session.add(dsf)
            db.session.flush()  # get dsf.file_id without committing

            file_path = datastore_get_standard_path(dsf, case_id)
            dsf.file_local_name = str(file_path)

            # Write PNG to disk before committing the DB record
            with open(str(file_path), "wb") as fh:
                fh.write(png_bytes)

            # Only commit once the file is safely on disk
            db.session.commit()

            self.log.info("Saved timeline PNG to datastore file_id=%s", dsf.file_id)
            return dsf.file_id

        except Exception as exc:
            self.log.error("Failed to save PNG to datastore: %s", exc, exc_info=True)
            try:
                db.session.rollback()
            except Exception:
                pass
            # Clean up any partially-written file
            try:
                if 'file_path' in locals() and file_path:
                    import os
                    if os.path.exists(str(file_path)):
                        os.remove(str(file_path))
            except Exception:
                pass
            return None

    _EXPORT_FOLDER = "Timeline Export"

    def _get_or_create_folder(self, db, case_id: int, root_path_id: int) -> int:
        """Return the path_id of the 'Timeline Export' folder, creating it if needed."""
        try:
            from app.models import DataStorePath
            from app.datamgmt.datastore.datastore_db import datastore_add_child_node

            folder = DataStorePath.query.filter_by(
                path_case_id=case_id,
                path_name=self._EXPORT_FOLDER,
                path_parent_id=root_path_id,
            ).first()
            if folder is None:
                err, msg, folder = datastore_add_child_node(root_path_id, self._EXPORT_FOLDER, case_id)
                if err or folder is None:
                    raise RuntimeError(msg)
                self.log.info("Created Datastore folder '%s'", self._EXPORT_FOLDER)
            return folder.path_id
        except Exception as exc:
            self.log.warning(
                "Could not find/create '%s' folder, falling back to root: %s",
                self._EXPORT_FOLDER, exc,
            )
            return root_path_id
