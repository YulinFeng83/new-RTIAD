# RetailVision / MOVA

RetailVision is the MOVA edge pipeline for multi-camera retail analytics. It detects and tracks people in camera feeds, classifies likely employees vs customers, stitches customer journeys across cameras, builds a shared Stage 1 store blueprint, supports Stage 2 per-camera calibration to that blueprint, and emits typed business events for Microsoft Fabric.

## What The System Does

- Detects people with YOLOv8
- Tracks them per camera with ByteTrack
- Classifies employee vs customer with the existing multi-strategy classifier
- Builds a shared Stage 1 store map from arranged camera tiles and projected zones
- Calibrates each camera to the shared blueprint in Stage 2 using homography
- Stitches journeys across cameras with:
  - OSNet appearance similarity
  - Stage 1 adjacency / overlap priors
  - temporal gating
  - calibrated floor-distance assist when Stage 2 is available
- Emits MOVA typed events to Event Hub:
  - `session_completed`
  - `zone_exited`
  - `door_crossed`
  - `floor_position_sample`

## Current MOVA Status

Implemented now:

- Stage 1 homepage blueprint builder
  - arrange live camera tiles
  - confirm overlap pairs
  - define shared floor-plan zones
  - project camera-local zones into the shared map
- Cross-camera stitching
  - adjacent handoff stitching
  - overlap active-active stitching
  - OSNet embeddings as the primary appearance signal
- Visit/session ownership
  - one `store_visit_id` across stitched segments
  - `segment_count` increments as new camera segments are linked
- Stage 2 calibration
  - per-camera snapshot-to-blueprint point matching
  - homography computation and validation
  - runtime calibrated floor coordinate mapping
- MOVA typed event contract
  - only the 4 intended MOVA event types are on the wire

Still intentionally deferred:

- advanced Stage 2 UX polish
- full 2D historical replay / heatmap UI
- any redesign of the current in-process footfall dashboard path

## Architecture

### Core runtime

- **YOLOv8** for person detection
- **ByteTrack** for per-camera tracking
- **OSNet** for appearance embeddings used by cross-camera stitching
- **FastAPI** for backend APIs, MJPEG feeds, snapshots, layout, and calibration
- **React + TypeScript + Vite** admin UI
- **Azure Event Hub** for typed event streaming
- **Microsoft Fabric / Eventhouse** for raw landing and update-policy filtering

### MOVA spatial model

#### Stage 1: shared blueprint

The homepage live camera grid is the Stage 1 authoring surface.

- Arrange live camera tiles to match real store layout
- Confirm adjacency / overlap relationships
- Draw camera-local zones
- Extract a clean shared 2D store map
- Save:
  - `spatial.floor_plan`
  - `spatial.camera_arrangement`
  - `spatial.camera_adjacency`
  - `spatial.camera_overlaps`
  - `spatial.floor_zones`

#### Stage 2: calibration

Each camera can be calibrated against the shared Stage 1 blueprint.

- Select camera
- load snapshot
- click 4 to 6 matching points on image and floor plan
- compute homography
- validate reprojection error
- save active calibration

This enables runtime image-point to floor-coordinate mapping.

### Cross-camera stitching

The stitcher uses two modes:

1. **Adjacent handoff stitching**
   - lost track on camera A
   - plausible new track on camera B
   - uses OSNet + Stage 1 adjacency + temporal gate

2. **Overlap active-active stitching**
   - confirmed-overlap camera pairs only
   - matches simultaneous active tracks across different angles
   - uses OSNet + overlap prior + temporal freshness

When both cameras have Stage 2 calibration, calibrated floor distance is also used as an additional stitch signal.

### Typed event model

The pipeline emits only these MOVA event types:

- `session_completed`
- `zone_exited`
- `door_crossed`
- `floor_position_sample`

These are written to unfiltered raw tables in Fabric, then filtered into facts by update policies using `max_employee_probability < 0.5`.

## Project Structure

```text
new-RTIAD/
  admin-ui/
    src/
      App.tsx
      components/
        LiveCameraBlueprintGrid.tsx
        CalibrationWorkbench.tsx
        CalibrationPointCanvas.tsx
        ZoneDrawer.tsx
        LiveFeed.tsx
      pages/
        CameraSetup.tsx
      store-context.tsx
  config/
    default_config.yaml
  fabric/
    mova_eventhouse_setup.kql
  src/
    main.py
    config.py
    pipeline.py
    api/
      app.py
      deps.py
      schemas.py
      routes/
        cameras.py
        calibration.py
        config.py
        footfall.py
        layout.py
        video_feed.py
    camera/
      manager.py
      stream.py
    counting/
      footfall_counter.py
    events/
      event_hub.py
      typed_events.py
      types.py
    position/
      camera_calibration.py
      floor_position_sampler.py
      homography_mapper.py
    reid/
      appearance_embedder.py
    rendering/
      overlay.py
    sessions/
      visit_session_manager.py
    stitching/
      cross_camera_stitcher.py
    tracking/
      track.py
      tracker.py
    zones/
      zone.py
      zone_manager.py
```

## Backend Setup

### Requirements

- Python 3.10+
- Node.js 18+ and npm
- Optional GPU / CUDA for faster inference

### Install Python dependencies

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Run the backend

```bash
python -m src.main
```

Or with a custom config:

```bash
python -m src.main path/to/config.yaml
```

Backend default:

- API: `http://localhost:8000`

## Frontend Setup

```bash
cd admin-ui
npm install
npm run dev
```

Frontend default:

- Admin UI: `http://localhost:5173`

## Main API Endpoints

### Video / camera

- `GET /api/v1/cameras`
- `GET /api/v1/cameras/{camera_id}/feed`
- `GET /api/v1/cameras/{camera_id}/snapshot`
- `POST /api/v1/cameras/{camera_id}/zones`
- `DELETE /api/v1/cameras/{camera_id}/zones/{zone_id}`

### Layout / Stage 1

- `GET /api/v1/stores/{store_id}/layout`
- `PUT /api/v1/stores/{store_id}/layout`

### Calibration / Stage 2

- `GET /api/v1/cameras/{camera_id}/calibration`
- `POST /api/v1/cameras/{camera_id}/calibration/preview`
- `PUT /api/v1/cameras/{camera_id}/calibration`

### Runtime stats / config

- `GET /api/v1/footfall/current`
- `GET /api/v1/config`
- `PUT /api/v1/config`

## Admin UI Workflow

### Stage 1: Store Map

Use the homepage live-grid workflow to:

- inspect live camera feeds
- enter edit mode
- drag / resize / rotate camera tiles
- confirm overlap pairs
- draw camera-local zones
- extract the clean 2D map
- add / edit / refine shared floor zones

### Stage 2: Calibration

Use the calibration workbench to:

- select a camera
- load a snapshot
- load the shared Stage 1 blueprint
- click matching point pairs
- preview homography quality
- save calibration

## Fabric / Eventhouse

The Fabric setup script lives in:

- [fabric/mova_eventhouse_setup.kql](fabric/mova_eventhouse_setup.kql)

Current design:

- raw tables are unfiltered source of truth
- update policies apply `max_employee_probability < 0.5`
- fact tables align to the MOVA ERD

Raw tables:

- `sessions_raw`
- `zone_exits_raw`
- `door_crossings_raw`
- `floor_positions_raw`

Fact tables:

- `fact_sessions`
- `fact_zone_visits`
- `fact_door_crossings`
- `fact_floor_positions`

## Event Contract

### Active wire event set

- `session_completed`
- `zone_exited`
- `door_crossed`
- `floor_position_sample`

### Important note

Legacy `footfall_updated` has been removed from the Event Hub wire path. The in-process footfall counter still exists for the current dashboard/API occupancy flow.

## Configuration Notes

Main configuration lives in:

- [config/default_config.yaml](config/default_config.yaml)

Key sections:

- `system`
- `cameras`
- `tracking`
- `reid`
- `employee_detection`
- `store`
- `spatial`
- `event_hub`

The config manager hot-reloads updates while the backend is running.

## Validation Basics

For a quick local check:

1. Run backend
2. Run admin UI
3. Open Stage 1 and confirm layout loads
4. Open Stage 2 and confirm calibration workbench loads
5. With Event Hub disabled, inspect local emit logs and confirm only:
   - `session_completed`
   - `zone_exited`
   - `door_crossed`
   - `floor_position_sample`

## Repo Notes

- Local recorded footage under `test data/` is useful for validation, but it is not required for the codebase itself.
- If you use local MP4 files as camera sources, update `config/default_config.yaml` to match your machine.
