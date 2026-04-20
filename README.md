# IRIS Timeline Export Module

An [IRIS](https://github.com/dfir-iris/iris-web) processor module that generates DFIR-Report-style timeline diagrams from marked case events and saves them to the case Datastore.

## Features

- Renders a **vertical timeline PNG** from events marked with the *Include in Export* custom attribute
- Alternating left/right layout with day-boundary markers, event categories, and multi-level comments
- Renders **4K 16:9 slide PNGs** (3840×2160, 5 events per slide) for direct import into PowerPoint — sub-boxes (comments) always extend away from the centre line so top and bottom events are symmetric
- Configurable title bar colour via the IRIS module settings UI
- Saves all exports to a *Timeline Export* folder in the case Datastore with a timestamped filename

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

## Usage

### 1. Mark events for export

Open any case event and set the **Include in Export** checkbox to `true` under the **Timeline Export** custom attribute tab. Optionally fill in **Export Comment** to add detail lines below the event in the diagram.

Comment syntax:

| Prefix | Result |
|---|---|
| (plain text) | Level-1 bullet |
| `- text` | Level-1 bullet |
| `-- text` | Level-2 indented bullet |

### 2. Trigger the export

On the case page, run one of the two manual triggers:

| Trigger | Output |
|---|---|
| **Export Timeline Diagram** | Single vertical PNG (2400 px wide) saved to Datastore |
| **Export Timeline (PPTX-ready 16:9)** | One or more 3840×2160 PNGs (5 events/slide) saved to Datastore |

A download link to each file appears in the task log after the export completes.

## Font configuration

The vertical renderer uses Lato fonts from the IRIS static assets (`/iriswebapp/app/static/assets/fonts/lato/`). The presentation renderer uses DejaVu fonts from `/usr/share/fonts/truetype/dejavu/`. For local development or non-standard deployments, override the Lato path with the `IRIS_FONT_DIR` environment variable:

```bash
export IRIS_FONT_DIR=/usr/share/fonts/truetype/dejavu
```

If no usable font is found the renderer falls back to Pillow's built-in bitmap font and logs a warning.

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
    ├── attribute_setup.py                 # Custom attribute provisioning and event helpers
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

## License

[LGPL-3.0](LICENSE)
