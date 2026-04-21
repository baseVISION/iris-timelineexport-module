"""
Setup script for iris-timelineexport-module demo/testing.

Run inside the IRIS worker container:
    podman exec iriswebapp_worker python3 /iriswebapp/dependencies/setup_demo.py

Tasks:
  1. Delete all timeline export images from case 11 (DB + disk).
  2. Re-export a fresh sample PNG for case 11.
  3. Create a new case with a complex set of timeline events for testing.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import sys

# ── Bootstrap Flask app context ───────────────────────────────────────────────
sys.path.insert(0, "/iriswebapp")
from app import app, db  # noqa: E402  (must be after sys.path tweak)

with app.app_context():
    # ── Imports that need the app context ─────────────────────────────────────
    from app.models import DataStoreFile, DataStorePath
    from app.models.authorization import User, CaseAccessLevel
    from app.models.cases import Cases, CasesEvent
    from app.datamgmt.datastore.datastore_db import (
        datastore_get_root,
        datastore_get_standard_path,
        datastore_add_child_node,
    )
    from app.datamgmt.manage.manage_groups_db import add_case_access_to_group
    from app.iris_engine.access_control.utils import ac_add_users_multi_effective_access
    from app.models.authorization import Group

    # ─────────────────────────────────────────────────────────────────────────
    # 0. Helpers
    # ─────────────────────────────────────────────────────────────────────────
    DEMO_CASE_ID = 11

    def _first_user_id() -> int:
        u = User.query.filter_by(active=True).order_by(User.id).first()
        if u is None:
            raise RuntimeError("No active user found")
        return u.id

    def _get_or_create_folder(case_id: int, root_path_id: int, folder_name: str) -> int:
        folder = DataStorePath.query.filter_by(
            path_case_id=case_id,
            path_name=folder_name,
            path_parent_id=root_path_id,
        ).first()
        if folder is None:
            err, msg, folder = datastore_add_child_node(root_path_id, folder_name, case_id)
            if err or folder is None:
                raise RuntimeError(f"Could not create folder '{folder_name}': {msg}")
        return folder.path_id

    def _save_png_to_datastore(png_bytes: bytes, filename: str, case_id: int) -> int:
        user_id = _first_user_id()
        root = datastore_get_root(case_id)
        if root is None:
            raise RuntimeError(f"No datastore root for case {case_id}")
        folder_id = _get_or_create_folder(case_id, root.path_id, "Timeline Export")

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

        db.session.add(dsf)
        db.session.flush()

        file_path = datastore_get_standard_path(dsf, case_id)
        dsf.file_local_name = str(file_path)
        os.makedirs(os.path.dirname(str(file_path)), exist_ok=True)
        with open(str(file_path), "wb") as fh:
            fh.write(png_bytes)
        db.session.commit()
        return dsf.file_id

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Delete all timeline exports from case 11
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[1/3] Cleaning up timeline exports from case 11 …")
    timeline_files = DataStoreFile.query.filter(
        DataStoreFile.file_case_id == DEMO_CASE_ID,
        DataStoreFile.file_original_name.like("timeline_%"),
    ).all()

    deleted_files = 0
    deleted_rows  = 0
    for f in timeline_files:
        path = f.file_local_name
        db.session.delete(f)
        deleted_rows += 1
        if path and os.path.exists(path):
            try:
                os.remove(path)
                deleted_files += 1
            except OSError as exc:
                print(f"  WARNING: could not remove {path}: {exc}")

    db.session.commit()
    print(f"  Removed {deleted_rows} DB records and {deleted_files} files from disk.")

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Render a fresh sample PNG for case 11
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[2/3] Generating fresh sample export for case 11 …")

    # Collect events in case 11 that are marked for export
    from iris_timelineexport_module.timeline_handler.attribute_setup import is_included
    from iris_timelineexport_module.timeline_handler.png_renderer import render as render_png
    from iris_timelineexport_module.timeline_handler.presentation_renderer import render_presentation

    all_events = (
        CasesEvent.query
        .filter(CasesEvent.case_id == DEMO_CASE_ID)
        .order_by(CasesEvent.event_date)
        .all()
    )
    marked = [ev for ev in all_events if is_included(ev)]
    print(f"  Found {len(marked)} / {len(all_events)} events marked for export.")

    case_obj  = db.session.get(Cases, DEMO_CASE_ID)
    case_name = case_obj.name.split(" - ", 1)[-1] if case_obj else f"Case {DEMO_CASE_ID}"

    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")

    png_bytes = render_png(marked, case_name, title_hex="#AE0C0C")
    fid = _save_png_to_datastore(png_bytes, f"timeline_export_{ts}.png", DEMO_CASE_ID)
    print(f"  PNG export saved → file_id={fid}  (/datastore/file/view/{fid}?cid={DEMO_CASE_ID})")

    slides = render_presentation(marked, case_name, title_hex="#AE0C0C", events_per_slide=5)
    for slide_bytes, slide_num in slides:
        sfid = _save_png_to_datastore(
            slide_bytes,
            f"timeline_presentation_{ts}_slide_{slide_num}.png",
            DEMO_CASE_ID,
        )
        print(f"  Slide {slide_num} saved → file_id={sfid}")

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Create a new case with a rich complex timeline for testing
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[3/3] Creating new test case with complex timeline …")

    # ── Create the case ───────────────────────────────────────────────────────
    user_obj  = User.query.filter_by(active=True).order_by(User.id).first()
    user_id   = user_obj.id
    client_id = case_obj.client_id if case_obj else 1

    new_case = Cases(
        name        = "Timeline Export – Complex Test",
        description = (
            "Automated test case for iris-timelineexport-module.\n\n"
            "Scenario: Multi-day ransomware intrusion. Events span 3 days, "
            "cover the full ATT&CK kill chain, and include multi-level comments "
            "to exercise the PNG and presentation renderers."
        ),
        soc_id   = "TLX-2026-001",
        user     = user_obj,
        client_id = client_id,
    )
    new_case.validate_on_build()
    new_case.save()
    db.session.commit()
    new_case_id = new_case.case_id
    print(f"  Created case → case_id={new_case_id} ({new_case.name})")

    # Grant access to all groups that have access to the demo case
    admin_group = Group.query.filter(Group.group_permissions.op('&')(1) == 1).first()
    if admin_group:
        add_case_access_to_group(
            group=admin_group,
            cases_list=[new_case_id],
            access_level=CaseAccessLevel.full_access.value,
        )
    ac_add_users_multi_effective_access(
        users_list=[user_id],
        cases_list=[new_case_id],
        access_level=CaseAccessLevel.full_access.value,
    )

    # Ensure datastore root path record exists
    root_path = DataStorePath()
    root_path.path_case_id   = new_case_id
    root_path.path_name      = "/"
    root_path.path_parent_id = None
    db.session.add(root_path)
    db.session.flush()

    # ── Custom attribute template ─────────────────────────────────────────────
    def _evt_attrs(include: bool, comment: str = "") -> dict:
        return {
            "Timeline Export": {
                "Include in Export": {"type": "input_checkbox", "value": include, "mandatory": False},
                "Export Comment":    {"type": "input_textfield", "value": comment, "mandatory": False},
                "Comment format":    {"type": "html", "value": "<small class='text-muted'>Prefix lines with <code>-</code> for level-1 bullets or <code>--</code> for level-2 bullets.</small>"},
            }
        }

    # ── Event definitions  (date, tz, title, category_id, include, comment) ──
    # category IDs: 4=Initial Access, 5=Execution, 6=Persistence, 7=Priv.Esc,
    #               8=Defense Evasion, 9=Credential Access, 10=Discovery,
    #               11=Lateral Movement, 12=Collection, 13=C2, 14=Exfiltration,
    #               15=Impact, 3=Remediation
    events_def = [
        # ── Day 1: 2026-04-01 ─────────────────────────────────────────────────
        (
            datetime.datetime(2026, 4, 1, 6, 12, 0), "UTC",
            "Spear-phishing email delivered", 4, True,
            "Sender: hr-noreply@contoso-corp[.]net\n"
            "- Subject: Q1 Salary Review Attached\n"
            "- Attachment: Q1_Review.docm (SHA256: 3a4b…f9c1)\n"
            "-- Macro present; auto-executes on open",
        ),
        (
            datetime.datetime(2026, 4, 1, 6, 34, 0), "UTC",
            "Victim opens malicious document", 5, True,
            "User: jsmith@victim.org (Finance)\n"
            "- Word spawns cmd.exe → powershell.exe\n"
            "-- PowerShell downloads stage-1 loader from 185.234.x.x\n"
            "- Beacon DLL dropped to %TEMP%\\MicrosoftUpdate.dll",
        ),
        (
            datetime.datetime(2026, 4, 1, 6, 35, 22), "UTC",
            "CobaltStrike beacon established", 13, True,
            "C2: https://update.windowssvc[.]net:443\n"
            "- Beacon type: HTTPS malleable profile\n"
            "- Sleep: 60s ± 20%\n"
            "-- Jitter applied; blends with browser traffic",
        ),
        (
            datetime.datetime(2026, 4, 1, 7, 2, 0), "UTC",
            "Scheduled task created for persistence", 6, True,
            "Task: \\Microsoft\\Windows\\MUICache\\UpdateTask\n"
            "- Runs MicrosoftUpdate.dll via rundll32 on logon\n"
            "- Created by: jsmith (standard user)",
        ),
        (
            datetime.datetime(2026, 4, 1, 7, 15, 0), "UTC",
            "Local user enumeration via net commands", 10, True,
            "net user /domain\nnet localgroup administrators\n"
            "- Output exfiltrated to C2 in beacon metadata",
        ),
        (
            datetime.datetime(2026, 4, 1, 8, 0, 0), "UTC",
            "Mimikatz run in memory (lsass dump)", 9, True,
            "Technique: sekurlsa::logonpasswords\n"
            "- Harvested: 3 NTLM hashes, 1 cleartext password\n"
            "-- Domain admin credential: VICTIM\\svc_backup\n"
            "-- Password: Backup@2025! (reused from AD)",
        ),
        (
            datetime.datetime(2026, 4, 1, 8, 45, 0), "UTC",
            "AV tampered — real-time protection disabled", 8, False,
            "Defender exclusion added via registry:\n"
            "HKLM\\SOFTWARE\\Microsoft\\Windows Defender\\Exclusions\\Paths",
        ),
        # ── Day 2: 2026-04-02 ─────────────────────────────────────────────────
        (
            datetime.datetime(2026, 4, 2, 1, 30, 0), "UTC",
            "Pass-the-hash lateral movement to DC", 11, True,
            "Source: WKSTN-042 (jsmith)\n"
            "Target: DC01.victim.org\n"
            "- Used svc_backup NTLM hash\n"
            "-- PsExec remote service created on DC01",
        ),
        (
            datetime.datetime(2026, 4, 2, 1, 55, 0), "UTC",
            "Second beacon on Domain Controller", 13, True,
            "DC01 → new HTTPS beacon to same C2\n"
            "- Elevated: SYSTEM\n"
            "- Persistence: registry Run key added under HKLM",
        ),
        (
            datetime.datetime(2026, 4, 2, 2, 10, 0), "UTC",
            "Domain-wide GPO modified for persistence", 6, True,
            "GPO: Default Domain Policy\n"
            "- Startup script added: \\\\DC01\\SYSVOL\\...\\startup.bat\n"
            "-- Drops loader to C:\\Windows\\Temp on each login\n"
            "-- Affects all workstations in domain",
        ),
        (
            datetime.datetime(2026, 4, 2, 3, 5, 0), "UTC",
            "File server share enumeration", 10, True,
            "net view /domain\nnet share on FS01\n"
            "- Identified Finance share: \\\\FS01\\Finance$\n"
            "- 2.3 TB of data accessible",
        ),
        (
            datetime.datetime(2026, 4, 2, 3, 20, 0), "UTC",
            "Sensitive data staged for exfiltration", 12, True,
            "7-Zip archive created: C:\\ProgramData\\backup.7z\n"
            "- Password: infected2026\n"
            "- Contents: Finance share docs, HR records, ERP exports\n"
            "-- Approx. 18 GB compressed",
        ),
        (
            datetime.datetime(2026, 4, 2, 4, 0, 0), "UTC",
            "Data exfiltrated via HTTPS to cloud storage", 14, True,
            "Destination: hxxps://file[.]io/uXkA9q\n"
            "- Method: curl upload in 512 MB chunks\n"
            "- Duration: ~47 minutes\n"
            "-- Completed at 04:47 UTC",
        ),
        (
            datetime.datetime(2026, 4, 2, 5, 10, 0), "UTC",
            "Ransomware binary downloaded to DC01", 5, True,
            "File: C:\\Windows\\Temp\\svchost32.exe\n"
            "- SHA256: 7f3e…a812\n"
            "- Packed with UPX; Ryuk-family variant",
        ),
        # ── Day 3: 2026-04-03 ─────────────────────────────────────────────────
        (
            datetime.datetime(2026, 4, 3, 3, 0, 0), "UTC",
            "Ransomware deployed domain-wide via GPO startup script", 15, True,
            "Execution method: SYSTEM-level startup script via modified GPO\n"
            "- Estimated 140 workstations and 6 servers encrypted\n"
            "-- File extension: .ryuk appended to all encrypted files\n"
            "-- Shadow copies deleted: vssadmin delete shadows /all /quiet",
        ),
        (
            datetime.datetime(2026, 4, 3, 3, 5, 0), "UTC",
            "Ransom note dropped", 15, True,
            "Filename: RyukReadMe.txt placed in every directory\n"
            "- BTC wallet: 1Abc…XyZ9\n"
            "- Demand: 45 BTC (~1.8M USD at time of incident)",
        ),
        (
            datetime.datetime(2026, 4, 3, 7, 30, 0), "UTC",
            "Incident detected by SOC — help desk tickets spike", 1, True,
            "First alert: user unable to open files, sees .ryuk extension\n"
            "- 47 tickets in 30 minutes\n"
            "- SOC escalated to IR team at 07:45 UTC",
        ),
        (
            datetime.datetime(2026, 4, 3, 8, 0, 0), "UTC",
            "Network isolation — affected segments quarantined", 3, True,
            "VLAN ACLs pushed to block inter-segment traffic\n"
            "- DC01 isolated from workstation VLAN\n"
            "- FS01 taken offline\n"
            "-- VPN gateway disabled to prevent spread",
        ),
        (
            datetime.datetime(2026, 4, 3, 10, 0, 0), "UTC",
            "IR team begins forensic imaging", 3, False,
            "Priority targets: DC01, WKSTN-042, FS01\n"
            "- FTK Imager used for live memory and disk captures",
        ),
        (
            datetime.datetime(2026, 4, 3, 16, 0, 0), "UTC",
            "Clean backups identified and restoration begins", 3, True,
            "Last clean backup: 2026-03-31 02:00 UTC\n"
            "- Restoration ETA: 72 hours for critical systems\n"
            "- Finance and HR prioritised",
        ),
    ]

    # ── Insert events ─────────────────────────────────────────────────────────
    for ev_date, ev_tz, ev_title, cat_id, include, comment in events_def:
        ev = CasesEvent()
        ev.case_id          = new_case_id
        ev.event_date       = ev_date
        ev.event_tz         = ev_tz
        ev.event_title      = ev_title
        ev.event_content    = ""
        ev.event_raw        = ""
        ev.event_source     = ""
        ev.event_in_summary = False
        ev.event_in_graph   = True
        ev.event_color      = ""
        ev.user_id          = user_id
        ev.event_added      = datetime.datetime.now(datetime.timezone.utc)
        ev.event_date_wtz   = ev_date
        ev.custom_attributes = _evt_attrs(include, comment)

        db.session.add(ev)
        db.session.flush()

        # Link category
        db.session.execute(
            db.text("INSERT INTO case_events_category (event_id, category_id) VALUES (:eid, :cid)"),
            {"eid": ev.event_id, "cid": cat_id},
        )

    db.session.commit()
    print(f"  Inserted {len(events_def)} events into case {new_case_id}.")

    # ── Render and save exports for the new case ──────────────────────────────
    new_case_obj   = db.session.get(Cases, new_case_id)
    new_case_name  = new_case_obj.name

    new_events     = (
        CasesEvent.query
        .filter(CasesEvent.case_id == new_case_id)
        .order_by(CasesEvent.event_date)
        .all()
    )
    new_marked = [e for e in new_events if is_included(e)]
    print(f"  {len(new_marked)} / {len(new_events)} events marked for export.")

    ts2 = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")

    new_png = render_png(new_marked, new_case_name.split(" - ", 1)[-1])
    nfid = _save_png_to_datastore(new_png, f"timeline_export_{ts2}.png", new_case_id)
    print(f"  PNG export saved → file_id={nfid}  (/datastore/file/view/{nfid}?cid={new_case_id})")

    new_slides = render_presentation(
        new_marked,
        new_case_name.split(" - ", 1)[-1],
        title_hex="#AE0C0C",
        events_per_slide=5,
    )
    for slide_bytes, slide_num in new_slides:
        sfid = _save_png_to_datastore(
            slide_bytes,
            f"timeline_presentation_{ts2}_slide_{slide_num}.png",
            new_case_id,
        )
        print(f"  Slide {slide_num} saved → file_id={sfid}")

    print(f"\nDone. New case: https://<IRIS_HOST>:8443/case?cid={new_case_id}")
