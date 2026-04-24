# IRIS Timeline Export Module

An [IRIS](https://github.com/dfir-iris/iris-web) processor module that generates DFIR-Report-style timeline diagrams from marked case events and saves them to the case Datastore.

## Features

- Renders a **vertical timeline PNG** from events marked with the *Include in Export* custom attribute
- Alternating left/right layout with day-boundary markers, event categories, and multi-level comments
- Renders **4K 16:9 slide PNGs** (3840×2160, 5 events per slide) for direct import into PowerPoint — sub-boxes (comments) always extend away from the centre line so top and bottom events are symmetric
- **Anonymized export** variants for both PNG and presentation — replaces text throughout all event titles, categories, and comments using a configurable key→value map; anonymized case name also applied to the title bar; output files are named with an `_anon` suffix
- **Per-event highlight** — check the *Highlight* checkbox on any event to draw a coloured border around it; border colour is configured globally in module settings
- **Per-category border colours** — assign a hex colour to any category name via module settings; events in that category receive a matching border in both renderers
- Configurable **title bar colour** via the IRIS module settings UI
- All exports saved to a *Timeline Export* folder in the case Datastore with timestamped filenames

## Requirements

| Component | Version |
|---|---|
| IRIS | ≥ 2.4.x |
| Python | ≥ 3.9 (container) |
| Pillow | ≥ 9.0 |
| pytz | any |

## Installation

### Using the build script (recommended)

```bash
git clone https://github.com/baseVISION/iris-timelineexport-module.git
cd iris-timelineexport-module
bash buildnpush2iris.sh        # installs into worker container and restarts it
bash buildnpush2iris.sh -a     # also installs into app container (required on first install)
```

The script builds the wheel, copies it into the running IRIS containers via Podman/Docker, and restarts the worker (and optionally the app container).

### Manual installation

```bash
git clone https://github.com/baseVISION/iris-timelineexport-module.git
cd iris-timelineexport-module

# Build the wheel from source
pip wheel . --no-deps -w dist/
WHL=$(ls dist/iris_timelineexport_module-*.whl | tail -1)
MODULE=$(basename "$WHL")

# Install into the worker container
docker cp "$WHL" iriswebapp_worker:/iriswebapp/dependencies/
docker exec iriswebapp_worker pip3 install "dependencies/$MODULE" --no-deps --force-reinstall

# Install into the app container (required on first install or config changes)
docker cp "$WHL" iriswebapp_app:/iriswebapp/dependencies/
docker exec iriswebapp_app pip3 install "dependencies/$MODULE" --no-deps --force-reinstall

# Restart containers
docker restart iriswebapp_worker iriswebapp_app
```

### Register in IRIS

Go to **Manage → Modules → Add module** and enter `iris_timelineexport_module`, then configure it under **Manage → Modules → IrisTimelineExport**.

## Configuration

All settings are in the IRIS UI under **Manage → Modules → IrisTimelineExport**.

| Parameter | Default | Description |
|---|---|---|
| Title bar color (hex) | `#AE0C0C` | Hex colour for the title bar, e.g. `#1A237E` for dark blue. |
| Highlight border color (hex) | `#FF8C00` | Border colour drawn around events with the *Highlight* checkbox set. |
| Category colors | *(empty)* | Multi-line field — one `Category Name=#rrggbb` entry per line. Lines starting with `#` are ignored as comments. |

### Category colors example

```
Initial Access=#8B0000
Execution=#B8860B
Persistence=#1A5276
Defence Evasion=#4A235A
```

## Usage

### 1. Mark events for export

Open any case event and fill in the **Timeline Export** custom attribute tab:

| Field | Type | Description |
|---|---|---|
| Include in Export | Checkbox | Must be checked for the event to appear in any export. |
| Highlight | Checkbox | Draws a coloured border around the event box (colour set in module config). |
| Export Comment | Text | Detail lines rendered below the event box. Supports bullet syntax (see below). |
| Override Category | Text | Replaces the event's IRIS category in the diagram only. |

Comment syntax:

| Prefix | Result |
|---|---|
| (plain text) | Level-1 bullet |
| `- text` | Level-1 bullet |
| `-- text` | Level-2 indented bullet |

### 2. Set up anonymization (optional)

Open the case and go to the **Timeline Export** custom attribute tab. Fill in the **Anonymization Map** textarea:

```
ACME Corp=Client A
192.168.1.50=10.0.0.1
john.doe=user1
```

Each line is a `find=replace` substitution applied (in order) to all event titles, categories, comments, and the case name during anonymized exports. Lines starting with `#` are skipped.

### 3. Trigger the export

On the case page, run one of the four manual triggers:

| Trigger | Output |
|---|---|
| **Export Timeline Diagram** | Full vertical PNG + one PNG per day, saved to Datastore |
| **Export Timeline (PPTX-ready 16:9)** | One or more 3840×2160 PNGs (5 events/slide) |
| **Export Timeline Diagram (Anonymized)** | Same as above but with all text substituted; files named `*_anon.png` |
| **Export Timeline (PPTX-ready 16:9, Anonymized)** | Same as above but anonymized; files named `*_anon.png` |

A download link to each file appears in the task log after the export completes.

## Font configuration

Both renderers use **DejaVu Sans** from `/usr/share/fonts/truetype/dejavu/`, which ships in the IRIS container and covers the full Latin Extended range including en/em dashes, smart quotes, and other common Unicode punctuation found in incident titles.

Override the font directory with the `IRIS_FONT_DIR` environment variable:

```bash
export IRIS_FONT_DIR=/path/to/fonts
```

Expected filenames: `DejaVuSans.ttf`, `DejaVuSans-Bold.ttf`. If no usable font is found the renderer falls back to Pillow's built-in bitmap font and logs a warning.

## Development

```bash
pip install pytest Pillow pytz
pytest tests/ -v
```

### Project structure

```
buildnpush2iris.sh                         # Build wheel + deploy to local containers (Podman/Docker)
iris_timelineexport_module/
├── __init__.py
├── IrisTimelineExportConfig.py            # Module metadata and configuration schema
├── IrisTimelineExportInterface.py         # Hook registration and dispatch
└── timeline_handler/
    ├── attribute_setup.py                 # Custom attribute provisioning and event/case helpers
    ├── png_renderer.py                    # Vertical DFIR-Report-style PNG renderer
    └── presentation_renderer.py          # 4K 16:9 slide PNG renderer
scripts/
├── setup_demo.py                          # Populate a demo case with complex test events
└── regen_slides.py                        # Regenerate all presentation slides in-place
tests/
├── test_attribute_setup.py
├── test_interface.py
└── test_png_renderer.py
```

## Changelog

### 1.1.1
- Switched both renderers from Lato to **DejaVu Sans** — covers full Latin Extended including en/em dashes and smart quotes, eliminating tofu replacement boxes for non-ASCII punctuation in event titles

### 1.1.0
- Added **Highlight** per-event checkbox with configurable border colour
- Added **per-category border colours** via module config (multiline `Category=#rrggbb` field)
- Added **anonymized export** triggers for both PNG and presentation renderers
  - Substitution map stored as a case-level custom attribute
  - Applied to event titles, categories, comments, and the case name in the title bar
  - Output files suffixed `_anon` to distinguish them from non-anonymized exports
- Added **Override Category** field per event to override the displayed category without changing the IRIS event
- Per-day PNGs now generated alongside the full timeline PNG
- Fixed: border widths in PNG renderer were unscaled (invisible after downsampling)
- Fixed: category colour priority logic in presentation renderer used fragile object-identity comparison

### 1.0.x
- Initial release with vertical PNG and 4K 16:9 presentation export

## License

[LGPL-3.0](LICENSE)

