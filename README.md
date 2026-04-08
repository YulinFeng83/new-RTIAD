# RetailVision

A production-grade, zero-fine-tuning retail analytics system that detects, tracks, and classifies people in camera feeds as employees or customers, counts foot traffic through configurable entry/exit zones, and renders all metrics directly on the video stream.

## Architecture

- **YOLOv8** for person detection (COCO pre-trained, class 0 only)
- **ByteTrack** for persistent multi-object tracking
- **CLIP ViT-B/32** for zero-shot employee/customer classification via dress code prompts
- **OpenCV** overlay for rendering bboxes, labels, zones, and counters on video
- **FastAPI** serves annotated MJPEG feed + zone CRUD API + config API
- **React + TypeScript + Vite** admin UI for multi-camera viewing and zone drawing
- **Azure Event Hub** (optional, off by default) for external event streaming

## Project Structure

```
retailvision/
  config/
    default_config.yaml          # All runtime configuration
  data/
    videos/                      # Place test MP4/AVI files here
  src/                           # Python backend
    main.py                      # Entry point — starts pipeline + API server
    config.py                    # Pydantic config models, YAML loader, hot-reload
    pipeline.py                  # Per-camera frame processing orchestrator
    models/
      detector.py                # YOLOv8 person detector wrapper
      employee_classifier.py     # Weighted multi-strategy ensemble + sticky labels
    strategies/
      base.py                    # Abstract classification strategy interface
      dress_code.py              # CLIP zero-shot dress code matching
      first_arrival.py           # Pre-opening time heuristic
    tracking/
      tracker.py                 # ByteTrack wrapper via Ultralytics
      track.py                   # Track dataclass (ID, history, label, etc.)
    zones/
      zone.py                    # Zone dataclass (polygon, type, direction)
      zone_manager.py            # Zone CRUD + per-frame crossing checks
      crossing_detector.py       # Point-in-polygon, direction determination
    counting/
      footfall_counter.py        # Customer enter/exit counting + occupancy
    camera/
      stream.py                  # Threaded video reader (RTSP, webcam, MP4 file)
      manager.py                 # Multi-camera lifecycle manager
    rendering/
      overlay.py                 # Draws bboxes, labels, zones, stats HUD on frames
    events/
      event_hub.py               # Azure Event Hub producer (configurable on/off)
      types.py                   # Event dataclasses (CrossingEvent, FootfallUpdate)
    api/
      app.py                     # FastAPI application factory
      deps.py                    # Shared application state
      schemas.py                 # Pydantic request/response schemas
      routes/
        video_feed.py            # GET /api/v1/cameras/{id}/feed (MJPEG stream)
        cameras.py               # Camera list + zone CRUD
        config.py                # Config GET/PUT with hot-reload
        footfall.py              # GET /api/v1/footfall/current
  admin-ui/                      # React + TypeScript + Vite
    src/
      App.tsx                    # Multi-camera grid view + navigation
      pages/
        CameraSetup.tsx          # Zone drawing interface for a single camera
      components/
        LiveFeed.tsx             # MJPEG feed viewer (<img> tag)
        ZoneDrawer.tsx           # Canvas polygon drawing overlay
```

## Prerequisites

- **Python 3.10+**
- **Node.js 18+** and npm (for the admin UI)
- **(Optional)** NVIDIA GPU with CUDA for faster inference — the system runs on CPU by default

## Python Backend Setup

```bash
# Navigate to the project root
cd retailvision

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # Linux/Mac

# Install Python dependencies
pip install -r requirements.txt
```

### Running the Backend

```bash
# From the retailvision/ directory
python -m src.main

# Or specify a custom config file
python -m src.main path/to/my_config.yaml

# Run the configured test cameras and save annotated outputs
python -m src.main --save-output --output-dir ./outputs

# Or run directly against all videos in a folder
python -m src.main --video-dir ./data/videos

# Or run one or more specific test videos
python -m src.main --video ./test\ data\video1.mp4 --video ./test\ data\video2.mp4

# Saved annotated outputs go to ./outputs by default
python -m src.main --video-dir ./data/videos --output-dir ./outputs
```

The backend starts on **http://localhost:8000** and exposes:

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/cameras/{id}/feed` | Annotated MJPEG video stream (open in browser) |
| `GET /api/v1/cameras` | List all cameras with their zones |
| `POST /api/v1/cameras/{id}/zones` | Create a zone (polygon + type + direction) |
| `DELETE /api/v1/cameras/{id}/zones/{zone_id}` | Delete a zone |
| `GET /api/v1/footfall/current` | Current entry/exit/occupancy stats |
| `GET /api/v1/config` | Get running configuration |
| `PUT /api/v1/config` | Update configuration (triggers hot-reload) |

## React Admin UI Setup

```bash
cd retailvision/admin-ui

# Install dependencies
npm install

# Start the dev server
npm run dev
```

The admin UI starts on **http://localhost:5173** and proxies API requests to the backend at `localhost:8000`.

### UI Features

- **Multi-camera grid** — all camera feeds displayed side-by-side in one window. Each feed shows bounding boxes, person labels (employee/customer), zone overlays, and a stats HUD (entries, exits, in-store count) rendered directly on the video by the backend.
- **Zone drawing** — click "Setup Zones" on any camera to open the zone drawing interface. Click to place polygon vertices, double-click to close, set direction arrow, choose zone type (entry/exit/bidirectional), and save.
- **Scene type badges** — each camera is tagged as indoor or outdoor (configured in YAML).

## Testing with Video Files

The system supports video files as a camera source for testing without real RTSP cameras.

### Simplest tester workflow

1. Use the configured test cameras in `config/default_config.yaml`, or put arbitrary videos in `data/videos/`.
2. Start the backend with `python -m src.main --save-output --output-dir ./outputs` for the curated config-driven test set.
3. Start the UI with `cd admin-ui` then `npm run dev`.
4. Open `http://localhost:5173`.

This keeps the original configured camera IDs, scene types, and logic intact while saving annotated outputs to `outputs/`.

If a tester wants to try arbitrary videos without editing YAML, use:

```bash
python -m src.main --video-dir ./data/videos --output-dir ./outputs
```

That mode automatically creates one camera per video file, disables Event Hub, loops the videos by default, and saves annotated outputs to `outputs/`.

If needed, output saving can be disabled:

```bash
python -m src.main --video-dir ./data/videos --no-save-output
```

### Step-by-step

1. **Get test videos** — place any MP4/AVI files with people walking in `data/videos/`:
   ```
   retailvision/data/videos/indoor.mp4
   retailvision/data/videos/outdoor.mp4
   ```

2. **Configure cameras** — either use `python -m src.main --video-dir ./data/videos` or edit `config/default_config.yaml` manually. A manual example looks like:
   ```yaml
   cameras:
     - id: "cam_indoor"
       url: "./data/videos/indoor.mp4"
       scene_type: "indoor"
       loop: true

     - id: "cam_outdoor"
       url: "./data/videos/outdoor.mp4"
       scene_type: "outdoor"
       loop: true
   ```

3. **Start the backend**:
   ```bash
   cd retailvision
  python -m src.main --video-dir ./data/videos
   ```

4. **View the raw MJPEG feeds** (no UI needed):
   - Indoor: http://localhost:8000/api/v1/cameras/cam_indoor/feed
   - Outdoor: http://localhost:8000/api/v1/cameras/cam_outdoor/feed

5. **Start the admin UI** (in a separate terminal):
   ```bash
   cd retailvision/admin-ui
   npm run dev
   ```
   Open http://localhost:5173 — both camera feeds appear in a grid.

6. **Draw entry/exit zones** — click "Setup Zones" on a camera, draw a polygon across the doorway, set zone type, and save. The backend immediately starts counting customers crossing that zone.

### Video source types

| Source | Config URL Example | Notes |
|--------|-------------------|-------|
| Video file | `"./data/videos/test.mp4"` | FPS-throttled to simulate real-time, loops by default |
| RTSP camera | `"rtsp://192.168.1.10:554/stream1"` | Live stream with auto-reconnect |
| Webcam | `"0"` | Local webcam by device index |

## Configuration

All settings are in `config/default_config.yaml`. The file is hot-reloadable — changes take effect without restarting the backend.

### Key sections

| Section | What it controls |
|---------|-----------------|
| `system` | Frame skip, target FPS, device (cpu/cuda), log level |
| `cameras` | Camera IDs, URLs (RTSP/file/webcam), scene type, zones |
| `detection` | YOLOv8 model, confidence threshold, IOU threshold |
| `tracking` | Tracker type (bytetrack/botsort), max lost frames |
| `employee_detection` | Classification threshold, sticky labels, strategy weights and prompts |
| `store` | Store name, opening/closing hours (for first-arrival heuristic) |
| `event_hub` | Enable/disable Azure Event Hub, connection string, batch settings |
| `overlay` | Toggle bboxes/labels/zones/stats HUD, colors, font size |

### Azure Event Hub

Event Hub is **disabled by default** for local testing. To enable:

```yaml
event_hub:
  enabled: true
  connection_string: "Endpoint=sb://..."
  event_hub_name: "retailvision-events"
```

When disabled, events are logged to the console instead.
