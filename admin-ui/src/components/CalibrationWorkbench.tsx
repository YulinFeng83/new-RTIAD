import { useEffect, useMemo, useState } from 'react'
import type { CameraInfo } from '../store-context'
import CalibrationPointCanvas from './CalibrationPointCanvas'

interface FloorPlanConfig {
  canvas_width: number
  canvas_height: number
  store_width_meters: number | null
  store_height_meters: number | null
  scale_meters_per_pixel: number | null
  origin: string
}

interface CameraArrangement {
  camera_id: string
  canvas_x: number
  canvas_y: number
  canvas_width: number
  canvas_height: number
  floor_x: number | null
  floor_y: number | null
  position: string
  coverage_area: string
  rotation_degrees: number
  opacity: number
  z_index: number
  source_frame_width: number | null
  source_frame_height: number | null
}

interface FloorZone {
  id: string
  zone_name: string
  zone_type: string
  source_mode: 'projected' | 'manual' | 'refined'
  promo_zone_flag: boolean
  map_x: number
  map_y: number
  map_width: number
  map_height: number
  source_camera_id: string | null
  source_zone_id: string | null
  map_polygon: number[][]
}

interface SpatialConfig {
  floor_plan: FloorPlanConfig
  camera_arrangement: CameraArrangement[]
  camera_adjacency: unknown[]
  camera_overlaps: unknown[]
  floor_zones: FloorZone[]
}

interface CameraCalibration {
  camera_id: string
  reference_points_image: number[][]
  reference_points_floor: number[][]
  homography_matrix: number[][]
  calibrated_at: string | null
  active_flag: boolean
}

interface CalibrationPreview {
  camera_id: string
  homography_matrix: number[][]
  reference_points_image: number[][]
  reference_points_floor: number[][]
  reprojection_error_pixels: number
  projected_floor_points: number[][]
  valid: boolean
  messages: string[]
}

interface Point {
  x: number
  y: number
}

type PendingSide = 'image' | 'floor'

const API_BASE = import.meta.env.VITE_API_BASE || `http://${window.location.hostname}:8000`

const DEFAULT_LAYOUT: SpatialConfig = {
  floor_plan: {
    canvas_width: 1200,
    canvas_height: 800,
    store_width_meters: null,
    store_height_meters: null,
    scale_meters_per_pixel: null,
    origin: 'bottom_left',
  },
  camera_arrangement: [],
  camera_adjacency: [],
  camera_overlaps: [],
  floor_zones: [],
}

export default function CalibrationWorkbench({
  cameras,
  storeId,
  storeName,
}: {
  cameras: CameraInfo[]
  storeId: string
  storeName: string
}) {
  const [layout, setLayout] = useState<SpatialConfig | null>(null)
  const [selectedCameraId, setSelectedCameraId] = useState(cameras[0]?.id || '')
  const [imagePoints, setImagePoints] = useState<Point[]>([])
  const [floorPoints, setFloorPoints] = useState<Point[]>([])
  const [imageWidth, setImageWidth] = useState(0)
  const [imageHeight, setImageHeight] = useState(0)
  const [pendingSide, setPendingSide] = useState<PendingSide>('image')
  const [preview, setPreview] = useState<CalibrationPreview | null>(null)
  const [savedCalibration, setSavedCalibration] = useState<CameraCalibration | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [snapshotVersion, setSnapshotVersion] = useState(0)

  useEffect(() => {
    if (!cameras.some((camera) => camera.id === selectedCameraId)) {
      setSelectedCameraId(cameras[0]?.id || '')
    }
  }, [cameras, selectedCameraId])

  useEffect(() => {
    if (!storeId) return
    setLoading(true)
    fetch(`/api/v1/stores/${encodeURIComponent(storeId)}/layout`)
      .then(async (res) => {
        if (!res.ok) throw new Error(await res.text())
        return (await res.json()) as SpatialConfig
      })
      .then((data) => setLayout(normalizeLayout(data, cameras)))
      .catch((err) => setError(`Failed to load Stage 1 blueprint: ${String(err)}`))
      .finally(() => setLoading(false))
  }, [storeId, cameras])

  useEffect(() => {
    if (!selectedCameraId) {
      setSavedCalibration(null)
      resetDraft()
      return
    }
    setLoading(true)
    setError('')
    setStatus('')
    fetch(`/api/v1/cameras/${encodeURIComponent(selectedCameraId)}/calibration`)
      .then(async (res) => {
        if (res.status === 404) {
          setSavedCalibration(null)
          resetDraft()
          return null
        }
        if (!res.ok) throw new Error(await res.text())
        return (await res.json()) as CameraCalibration
      })
      .then((data) => {
        if (!data) return
        setSavedCalibration(data)
        const nextImagePoints = toPoints(data.reference_points_image)
        const nextFloorPoints = toPoints(data.reference_points_floor)
        setImagePoints(nextImagePoints)
        setFloorPoints(nextFloorPoints)
        setPendingSide(nextImagePoints.length === nextFloorPoints.length ? 'image' : 'floor')
        setPreview(null)
        setStatus('Loaded saved calibration points. Recompute preview before saving changes.')
      })
      .catch((err) => setError(`Failed to load camera calibration: ${String(err)}`))
      .finally(() => setLoading(false))
  }, [selectedCameraId])

  const selectedCamera = cameras.find((camera) => camera.id === selectedCameraId) || null
  const floorPlan = layout?.floor_plan || DEFAULT_LAYOUT.floor_plan
  const snapshotUrl = selectedCameraId
    ? `${API_BASE}/api/v1/cameras/${encodeURIComponent(selectedCameraId)}/snapshot?v=${snapshotVersion}`
    : ''
  const canCompute =
    Boolean(selectedCameraId) &&
    imageWidth > 0 &&
    imageHeight > 0 &&
    imagePoints.length >= 4 &&
    imagePoints.length === floorPoints.length &&
    pendingSide === 'image'
  const canSave = Boolean(preview?.valid) && !saving && Boolean(selectedCameraId)

  const projectedPreviewPoints = useMemo(
    () => toPoints(preview?.projected_floor_points || []),
    [preview],
  )

  const handleAddImagePoint = (point: Point) => {
    if (pendingSide !== 'image') {
      setStatus('Click the matching point on the floor map next.')
      return
    }
    setImagePoints((current) => [...current, point])
    setPendingSide('floor')
    setPreview(null)
    setStatus(`Image point ${imagePoints.length + 1} added. Now click the same location on the floor map.`)
    setError('')
  }

  const handleAddFloorPoint = (point: Point) => {
    if (pendingSide !== 'floor') {
      setStatus('Click the camera snapshot first, then the matching floor-map point.')
      return
    }
    if (floorPoints.length >= imagePoints.length) {
      setStatus('Add another image point before adding more floor-map points.')
      return
    }
    setFloorPoints((current) => [...current, point])
    setPendingSide('image')
    setPreview(null)
    setStatus(`Point pair ${floorPoints.length + 1} captured.`)
    setError('')
  }

  const computePreview = async () => {
    if (!canCompute || !selectedCameraId) return
    setLoading(true)
    setError('')
    setStatus('')
    try {
      const res = await fetch(`/api/v1/cameras/${encodeURIComponent(selectedCameraId)}/calibration/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          reference_points_image: imagePoints.map(toArrayPoint),
          reference_points_floor: floorPoints.map(toArrayPoint),
          image_width: imageWidth,
          image_height: imageHeight,
        }),
      })
      if (!res.ok) {
        throw new Error(await res.text())
      }
      const data = (await res.json()) as CalibrationPreview
      setPreview(data)
      setStatus(
        data.valid
          ? `Calibration preview looks good. Mean reprojection error: ${data.reprojection_error_pixels.toFixed(2)}px.`
          : 'Calibration preview is invalid. Adjust the point pairs and try again.',
      )
    } catch (err) {
      setError(`Failed to compute calibration preview: ${String(err)}`)
      setPreview(null)
    } finally {
      setLoading(false)
    }
  }

  const saveCalibration = async () => {
    if (!canSave || !selectedCameraId) return
    setSaving(true)
    setError('')
    setStatus('')
    try {
      const res = await fetch(`/api/v1/cameras/${encodeURIComponent(selectedCameraId)}/calibration`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          reference_points_image: imagePoints.map(toArrayPoint),
          reference_points_floor: floorPoints.map(toArrayPoint),
          image_width: imageWidth,
          image_height: imageHeight,
          active_flag: true,
        }),
      })
      if (!res.ok) {
        throw new Error(await res.text())
      }
      const data = (await res.json()) as CameraCalibration
      setSavedCalibration(data)
      setStatus(`Calibration saved for ${data.camera_id}. Runtime floor mapping is now available for this camera.`)
    } catch (err) {
      setError(`Failed to save calibration: ${String(err)}`)
    } finally {
      setSaving(false)
    }
  }

  const clearPoints = () => {
    resetDraft()
    setSavedCalibration((current) => current)
    setStatus('Point pairs cleared. Start again from the camera image.')
    setError('')
  }

  const pairedPoints = Math.min(imagePoints.length, floorPoints.length)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-xs uppercase text-gray-500">{storeName}</p>
          <h2 className="mt-1 text-lg font-semibold">Stage 2 Camera Calibration</h2>
          <p className="mt-1 text-sm text-gray-400">
            Match 4 to 6 points between the camera snapshot and the shared Stage 1 blueprint.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-sm text-gray-300">
            Camera
            <select
              value={selectedCameraId}
              onChange={(event) => setSelectedCameraId(event.target.value)}
              className="ml-2 rounded border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white"
            >
              {cameras.map((camera) => (
                <option key={camera.id} value={camera.id}>
                  {camera.id}
                </option>
              ))}
            </select>
          </label>
          <button
            onClick={() => setSnapshotVersion((current) => current + 1)}
            disabled={!selectedCameraId}
            className="rounded border border-gray-700 bg-gray-800 px-4 py-2 text-sm font-medium text-gray-100 hover:bg-gray-700 disabled:opacity-50"
          >
            Refresh Snapshot
          </button>
          <button
            onClick={clearPoints}
            className="rounded border border-gray-700 bg-gray-800 px-4 py-2 text-sm font-medium text-gray-100 hover:bg-gray-700"
          >
            Clear Points
          </button>
          <button
            onClick={computePreview}
            disabled={!canCompute || loading}
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:bg-gray-700"
          >
            {loading ? 'Computing...' : 'Compute Calibration'}
          </button>
          <button
            onClick={saveCalibration}
            disabled={!canSave}
            className="rounded bg-teal-700 px-4 py-2 text-sm font-medium text-white hover:bg-teal-600 disabled:bg-gray-700"
          >
            {saving ? 'Saving...' : 'Save Calibration'}
          </button>
        </div>
      </div>

      {status && <div className="rounded border border-teal-700 bg-teal-950/40 p-3 text-sm text-teal-100">{status}</div>}
      {error && <div className="rounded border border-red-700 bg-red-950/40 p-3 text-sm text-red-200">{error}</div>}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_1fr_320px]">
        <CalibrationPointCanvas
          width={imageWidth}
          height={imageHeight}
          points={imagePoints}
          onAddPoint={handleAddImagePoint}
          disabled={!selectedCameraId}
          title="Camera Snapshot"
          subtitle={
            pendingSide === 'image'
              ? 'Click the next point on the snapshot.'
              : 'Waiting for the matching floor-map point.'
          }
        >
          {selectedCamera ? (
            <img
              key={snapshotUrl}
              src={snapshotUrl}
              alt={`Calibration snapshot for ${selectedCamera.id}`}
              className="h-full w-full object-contain"
              onLoad={(event) => {
                setImageWidth(event.currentTarget.naturalWidth)
                setImageHeight(event.currentTarget.naturalHeight)
              }}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-gray-500">
              Select a camera to start calibration.
            </div>
          )}
        </CalibrationPointCanvas>

        <CalibrationPointCanvas
          width={floorPlan.canvas_width}
          height={floorPlan.canvas_height}
          points={floorPoints}
          ghostPoints={preview ? projectedPreviewPoints : []}
          onAddPoint={handleAddFloorPoint}
          disabled={!layout}
          title="Shared Stage 1 Blueprint"
          subtitle={
            pendingSide === 'floor'
              ? 'Click the matching point on the shared map.'
              : 'Waiting for the next snapshot point.'
          }
        >
          <BlueprintPreview layout={layout || DEFAULT_LAYOUT} selectedCameraId={selectedCameraId} />
        </CalibrationPointCanvas>

        <aside className="space-y-4 rounded border border-gray-800 bg-gray-900 p-4">
          <section>
            <h3 className="text-sm font-semibold text-gray-100">Pairing Status</h3>
            <div className="mt-3 space-y-2 text-sm text-gray-300">
              <p>Pending side: <span className="font-medium text-white">{pendingSide === 'image' ? 'camera snapshot' : 'shared map'}</span></p>
              <p>Captured pairs: <span className="font-medium text-white">{pairedPoints}</span></p>
              <p>Snapshot size: <span className="font-medium text-white">{imageWidth > 0 ? `${imageWidth} x ${imageHeight}` : 'not loaded yet'}</span></p>
              <p>Blueprint scale: <span className="font-medium text-white">{floorPlan.scale_meters_per_pixel ? `${floorPlan.scale_meters_per_pixel.toFixed(4)} m/px` : 'missing Stage 1 scale'}</span></p>
            </div>
          </section>

          <section>
            <h3 className="text-sm font-semibold text-gray-100">Point Pairs</h3>
            <ol className="mt-3 space-y-2 text-xs text-gray-400">
              {Array.from({ length: Math.max(imagePoints.length, floorPoints.length) }, (_, index) => (
                <li key={`pair-${index + 1}`} className="rounded border border-gray-800 bg-gray-950 p-2">
                  <p className="font-medium text-gray-200">Pair {index + 1}</p>
                  <p>Image: {formatPoint(imagePoints[index])}</p>
                  <p>Floor: {formatPoint(floorPoints[index])}</p>
                </li>
              ))}
              {imagePoints.length === 0 && (
                <li className="rounded border border-dashed border-gray-800 p-3 text-gray-500">
                  Start by clicking a point on the camera snapshot.
                </li>
              )}
            </ol>
          </section>

          <section>
            <h3 className="text-sm font-semibold text-gray-100">Validation</h3>
            {preview ? (
              <div className="mt-3 space-y-2 text-sm">
                <p className={preview.valid ? 'text-teal-300' : 'text-red-300'}>
                  {preview.valid ? 'Preview valid' : 'Preview invalid'}
                </p>
                <p className="text-gray-300">
                  Reprojection error: {preview.reprojection_error_pixels.toFixed(2)}px
                </p>
                {preview.messages.length > 0 && (
                  <ul className="list-disc space-y-1 pl-5 text-xs text-gray-400">
                    {preview.messages.map((message, index) => (
                      <li key={`message-${index + 1}`}>{message}</li>
                    ))}
                  </ul>
                )}
              </div>
            ) : (
              <p className="mt-3 text-sm text-gray-500">
                Compute a preview to validate the homography before saving.
              </p>
            )}
          </section>

          <section>
            <h3 className="text-sm font-semibold text-gray-100">Saved Calibration</h3>
            {savedCalibration ? (
              <div className="mt-3 space-y-2 text-sm text-gray-300">
                <p>Status: <span className="font-medium text-white">{savedCalibration.active_flag ? 'active' : 'inactive'}</span></p>
                <p>Calibrated at: <span className="font-medium text-white">{savedCalibration.calibrated_at || 'unknown'}</span></p>
                <p>Stored pairs: <span className="font-medium text-white">{savedCalibration.reference_points_image.length}</span></p>
              </div>
            ) : (
              <p className="mt-3 text-sm text-gray-500">No saved calibration for this camera yet.</p>
            )}
          </section>
        </aside>
      </div>
    </div>
  )

  function resetDraft() {
    setImagePoints([])
    setFloorPoints([])
    setPendingSide('image')
    setPreview(null)
  }
}

function BlueprintPreview({
  layout,
  selectedCameraId,
}: {
  layout: SpatialConfig
  selectedCameraId: string
}) {
  return (
    <svg
      viewBox={`0 0 ${layout.floor_plan.canvas_width} ${layout.floor_plan.canvas_height}`}
      className="h-full w-full"
      preserveAspectRatio="none"
    >
      <rect
        x={0}
        y={0}
        width={layout.floor_plan.canvas_width}
        height={layout.floor_plan.canvas_height}
        fill="#030712"
      />
      <path
        d={gridPath(layout.floor_plan.canvas_width, layout.floor_plan.canvas_height, 80)}
        stroke="rgba(148,163,184,0.16)"
        strokeWidth={1}
      />
      {layout.floor_zones.map((zone) => (
        <g key={zone.id}>
          {zone.map_polygon.length > 0 ? (
            <polygon
              points={zone.map_polygon.map((point) => `${point[0]},${point[1]}`).join(' ')}
              fill={zoneFill(zone.zone_type)}
              stroke="#94a3b8"
              strokeWidth={2}
            />
          ) : (
            <rect
              x={zone.map_x}
              y={zone.map_y}
              width={zone.map_width}
              height={zone.map_height}
              fill={zoneFill(zone.zone_type)}
              stroke="#94a3b8"
              strokeWidth={2}
            />
          )}
          <text
            x={zone.map_x + 8}
            y={zone.map_y + 18}
            fill="#e2e8f0"
            fontSize={16}
            fontWeight={600}
          >
            {zone.zone_name || zone.id}
          </text>
        </g>
      ))}
      {layout.camera_arrangement.map((tile) => (
        <g key={tile.camera_id}>
          <rect
            x={tile.canvas_x}
            y={tile.canvas_y}
            width={tile.canvas_width}
            height={tile.canvas_height}
            fill={tile.camera_id === selectedCameraId ? 'rgba(59,130,246,0.28)' : 'rgba(15,23,42,0.55)'}
            stroke={tile.camera_id === selectedCameraId ? '#60a5fa' : '#475569'}
            strokeWidth={tile.camera_id === selectedCameraId ? 3 : 2}
            rx={10}
            ry={10}
          />
          <text
            x={tile.canvas_x + 12}
            y={tile.canvas_y + 24}
            fill="#f8fafc"
            fontSize={18}
            fontWeight={700}
          >
            {tile.camera_id}
          </text>
        </g>
      ))}
    </svg>
  )
}

function normalizeLayout(layout: SpatialConfig, cameras: CameraInfo[]): SpatialConfig {
  return {
    ...DEFAULT_LAYOUT,
    ...layout,
    camera_arrangement: layout.camera_arrangement?.filter((tile) => cameras.some((camera) => camera.id === tile.camera_id)) || [],
    floor_zones: layout.floor_zones || [],
  }
}

function toPoints(points: number[][]): Point[] {
  return points.map(([x, y]) => ({ x, y }))
}

function toArrayPoint(point: Point) {
  return [point.x, point.y]
}

function formatPoint(point?: Point) {
  if (!point) return 'pending'
  return `${point.x.toFixed(1)}, ${point.y.toFixed(1)}`
}

function zoneFill(zoneType: string) {
  switch (zoneType) {
    case 'checkout':
    case 'counter':
    case 'service_counter':
      return 'rgba(20,184,166,0.22)'
    case 'promo':
      return 'rgba(245,158,11,0.22)'
    case 'entrance':
      return 'rgba(59,130,246,0.2)'
    case 'staff':
    case 'back_of_house':
      return 'rgba(239,68,68,0.22)'
    default:
      return 'rgba(148,163,184,0.16)'
  }
}

function gridPath(width: number, height: number, step: number) {
  const parts: string[] = []
  for (let x = step; x < width; x += step) {
    parts.push(`M ${x} 0 L ${x} ${height}`)
  }
  for (let y = step; y < height; y += step) {
    parts.push(`M 0 ${y} L ${width} ${y}`)
  }
  return parts.join(' ')
}
