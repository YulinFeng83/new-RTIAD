import { forwardRef, useEffect, useMemo, useRef, useState } from 'react'
import LiveFeed from './LiveFeed'
import CameraSetup from '../pages/CameraSetup'
import type { CameraInfo } from '../store-context'

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

interface CameraAdjacency {
  camera_a_id: string
  camera_b_id: string
  edge_a: string
  edge_b: string
  distance_pixels: number
  distance_meters: number | null
}

interface CameraOverlap {
  camera_a_id: string
  camera_b_id: string
  confirmed_overlap: boolean
  primary_camera_id: string
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
  camera_adjacency: CameraAdjacency[]
  camera_overlaps: CameraOverlap[]
  floor_zones: FloorZone[]
}

interface Point {
  x: number
  y: number
}

type DragState = {
  kind: 'move' | 'resize'
  cameraId: string
  pointer: Point
  tile: CameraArrangement
}

type GridMode = 'live' | 'map' | 'edit'
type MapTool = 'select' | 'add'
type MapDragState =
  | {
      kind: 'move-zone'
      zoneId: string
      pointer: Point
      zone: FloorZone
    }
  | {
      kind: 'resize-zone'
      zoneId: string
      pointer: Point
      zone: FloorZone
    }
  | null

const DEFAULT_FLOOR_PLAN: FloorPlanConfig = {
  canvas_width: 1200,
  canvas_height: 800,
  store_width_meters: null,
  store_height_meters: null,
  scale_meters_per_pixel: null,
  origin: 'bottom_left',
}

export default function LiveCameraBlueprintGrid({
  cameras,
  storeId,
  storeName,
  onSaved,
}: {
  cameras: CameraInfo[]
  storeId: string
  storeName: string
  onSaved: () => Promise<void>
}) {
  const canvasRef = useRef<HTMLDivElement | null>(null)
  const mapCanvasRef = useRef<HTMLDivElement | null>(null)
  const [mode, setMode] = useState<GridMode>('live')
  const [savedLayout, setSavedLayout] = useState<SpatialConfig | null>(null)
  const [draftLayout, setDraftLayout] = useState<SpatialConfig | null>(null)
  const [selectedCameraId, setSelectedCameraId] = useState('')
  const [cameraZoneEditorCameraId, setCameraZoneEditorCameraId] = useState<string | null>(null)
  const [selectedSharedZoneId, setSelectedSharedZoneId] = useState<string | null>(null)
  const [mapTool, setMapTool] = useState<MapTool>('select')
  const [drag, setDrag] = useState<DragState | null>(null)
  const [mapDrag, setMapDrag] = useState<MapDragState>(null)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!storeId) return
    fetch(`/api/v1/stores/${encodeURIComponent(storeId)}/layout`)
      .then((res) => res.json())
      .then((data: SpatialConfig) => {
        const normalized = normalizeLayout(data, cameras)
        setSavedLayout(normalized)
        setDraftLayout(normalized)
        setSelectedCameraId(normalized.camera_arrangement[0]?.camera_id || '')
      })
      .catch((err) => setError(`Failed to load store map: ${String(err)}`))
  }, [storeId, cameras])

  const layout = draftLayout || normalizeLayout({} as SpatialConfig, cameras)
  const adjacency = useMemo(
    () => deriveAdjacency(layout.camera_arrangement, layout.floor_plan.scale_meters_per_pixel || 0),
    [layout.camera_arrangement, layout.floor_plan.scale_meters_per_pixel],
  )
  const overlapCandidates = useMemo(
    () => deriveOverlapCandidates(layout.camera_arrangement, layout.camera_overlaps),
    [layout.camera_arrangement, layout.camera_overlaps],
  )
  const projectedZones = useMemo(
    () => reprojectFloorZones(layout.floor_zones, layout.camera_arrangement, cameras),
    [layout.floor_zones, layout.camera_arrangement, cameras],
  )
  const selectedTile = layout.camera_arrangement.find((tile) => tile.camera_id === selectedCameraId)
  const selectedSharedZone = projectedZones.find((zone) => zone.id === selectedSharedZoneId) || null
  const zoneEditorCamera = cameras.find((camera) => camera.id === cameraZoneEditorCameraId)

  const enterEditMode = () => {
    setDraftLayout(savedLayout ? normalizeLayout(savedLayout, cameras) : normalizeLayout({} as SpatialConfig, cameras))
    setMode('edit')
    setDirty(false)
    setError('')
    setStatus('')
  }

  const cancelEdit = () => {
    setDraftLayout(savedLayout ? normalizeLayout(savedLayout, cameras) : normalizeLayout({} as SpatialConfig, cameras))
    setMode('live')
    setDirty(false)
    setError('')
    setStatus('')
  }

  const updateFloorPlan = (patch: Partial<FloorPlanConfig>) => {
    setDraftLayout((current) => {
      const base = current || normalizeLayout({} as SpatialConfig, cameras)
      const nextFloorPlan = normalizeFloorPlan({ ...base.floor_plan, ...patch })
      return {
        ...base,
        floor_plan: nextFloorPlan,
        camera_arrangement: base.camera_arrangement.map((tile) =>
          withFloorPosition(clampTile(tile, nextFloorPlan), nextFloorPlan),
        ),
        floor_zones: base.floor_zones.map((zone) => clampZone(zone, nextFloorPlan)),
      }
    })
    setDirty(true)
  }

  const updateTile = (cameraId: string, patch: Partial<CameraArrangement>, markDirty = true) => {
    setDraftLayout((current) => {
      const base = current || normalizeLayout({} as SpatialConfig, cameras)
      return {
        ...base,
        camera_arrangement: base.camera_arrangement.map((tile) =>
          tile.camera_id === cameraId
            ? withFloorPosition(clampTile({ ...tile, ...patch }, base.floor_plan), base.floor_plan)
            : tile,
        ),
      }
    })
    if (markDirty) setDirty(true)
  }

  const toggleOverlap = (candidate: CameraOverlap, confirmed: boolean) => {
    setDraftLayout((current) => {
      const base = current || normalizeLayout({} as SpatialConfig, cameras)
      const key = pairKey(candidate.camera_a_id, candidate.camera_b_id)
      const nextOverlaps = base.camera_overlaps.filter(
        (item) => pairKey(item.camera_a_id, item.camera_b_id) !== key,
      )
      if (confirmed) {
        nextOverlaps.push({ ...candidate, confirmed_overlap: true })
      }
      return { ...base, camera_overlaps: nextOverlaps }
    })
    setDirty(true)
  }

  const openCameraZoneEditor = (cameraId: string) => {
    setCameraZoneEditorCameraId(cameraId)
    setSelectedCameraId(cameraId)
    setError('')
    setStatus('')
  }

  const closeCameraZoneEditor = () => {
    setCameraZoneEditorCameraId(null)
  }

  const handleCameraZonesSaved = async () => {
    await onSaved()
    const res = await fetch(`/api/v1/stores/${encodeURIComponent(storeId)}/layout`)
    const data = (await res.json()) as SpatialConfig
    const normalized = normalizeLayout(data, cameras)
    setSavedLayout(normalized)
    setDraftLayout(normalized)
    setDirty(false)
    setStatus('Camera zones updated.')
  }

  const updateFloorZone = (zoneId: string, updater: (zone: FloorZone) => FloorZone) => {
    setDraftLayout((current) => {
      const base = current || normalizeLayout({} as SpatialConfig, cameras)
      return {
        ...base,
        floor_zones: base.floor_zones.map((zone) => {
          if (zone.id !== zoneId) return zone
          const nextZone = clampZone(updater(zone), base.floor_plan)
          return normalizeZone(nextZone)
        }),
      }
    })
    setDirty(true)
  }

  const addManualZone = () => {
    const id = `manual_zone_${Date.now()}`
    const width = Math.max(120, layout.floor_plan.canvas_width * 0.12)
    const height = Math.max(80, layout.floor_plan.canvas_height * 0.1)
    const x = (layout.floor_plan.canvas_width - width) / 2
    const y = (layout.floor_plan.canvas_height - height) / 2
    const zone = createRectZone({
      id,
      zone_name: `Zone ${projectedZones.length + 1}`,
      zone_type: 'aisle',
      source_mode: 'manual',
      promo_zone_flag: false,
      x,
      y,
      width,
      height,
    })
    setDraftLayout((current) => {
      const base = current || normalizeLayout({} as SpatialConfig, cameras)
      return { ...base, floor_zones: [...base.floor_zones, zone] }
    })
    setSelectedSharedZoneId(id)
    setDirty(true)
    setMapTool('select')
  }

  const deleteSelectedZone = () => {
    if (!selectedSharedZoneId) return
    setDraftLayout((current) => {
      const base = current || normalizeLayout({} as SpatialConfig, cameras)
      return {
        ...base,
        floor_zones: base.floor_zones.filter((zone) => zone.id !== selectedSharedZoneId),
      }
    })
    setSelectedSharedZoneId(null)
    setDirty(true)
  }

  const extract2DMap = () => {
    const projected = projectZonesFromTiles(layout, cameras)
    if (projected.length === 0) {
      const reasons = cameras
        .map((camera) => `${camera.id}: ${camera.zones.length === 0 ? 'draw camera-local zones first' : 'live tile dimensions not ready'}`)
        .join('; ')
      setError(`No 2D zones were extracted. ${reasons}`)
      setStatus('')
      return
    }

    setDraftLayout((current) => {
      const base = current || layout
      const manualZones = base.floor_zones.filter((zone) => zone.source_mode === 'manual')
      const refinedZones = base.floor_zones.filter((zone) => zone.source_mode === 'refined')
      const refinedBySource = new Map(
        refinedZones
          .filter((zone) => zone.source_camera_id && zone.source_zone_id)
          .map((zone) => [sourceZoneKey(zone.source_camera_id, zone.source_zone_id), zone]),
      )
      const nextProjected = projected.filter((zone) => !refinedBySource.has(sourceZoneKey(zone.source_camera_id, zone.source_zone_id)))
      return {
        ...base,
        camera_adjacency: adjacency,
        camera_overlaps: overlapCandidates.filter((candidate) => candidate.confirmed_overlap),
        floor_zones: [...manualZones, ...refinedZones, ...nextProjected].map((zone) => clampZone(zone, base.floor_plan)),
      }
    })
    setDirty(true)
    setError('')
    setStatus(`Extracted ${projected.length} zone${projected.length === 1 ? '' : 's'} into the 2D map.`)
  }

  const saveLayout = async () => {
    setSaving(true)
    setError('')
    setStatus('')
    try {
      const payload: SpatialConfig = {
        ...layout,
        camera_adjacency: adjacency,
        camera_overlaps: overlapCandidates.filter((candidate) => candidate.confirmed_overlap),
        floor_zones: projectedZones,
      }
      const res = await fetch(`/api/v1/stores/${encodeURIComponent(storeId)}/layout`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        setError(await res.text())
        return
      }
      const saved = normalizeLayout((await res.json()) as SpatialConfig, cameras)
      setSavedLayout(saved)
      setDraftLayout(saved)
      setDirty(false)
      setStatus('Store map saved.')
      setMode('map')
      await onSaved()
    } finally {
      setSaving(false)
    }
  }

  const beginDrag = (
    event: React.PointerEvent<HTMLElement>,
    tile: CameraArrangement,
    kind: 'move' | 'resize',
  ) => {
    if (mode !== 'edit') return
    event.preventDefault()
    event.stopPropagation()
    setSelectedCameraId(tile.camera_id)
    setDrag({ kind, cameraId: tile.camera_id, pointer: canvasPoint(event), tile })
    canvasRef.current?.setPointerCapture(event.pointerId)
  }

  const onCanvasPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!drag) return
    const point = canvasPoint(event)
    const dx = point.x - drag.pointer.x
    const dy = point.y - drag.pointer.y
    if (drag.kind === 'move') {
      updateTile(drag.cameraId, {
        canvas_x: drag.tile.canvas_x + dx,
        canvas_y: drag.tile.canvas_y + dy,
      })
    } else {
      updateTile(drag.cameraId, {
        canvas_width: drag.tile.canvas_width + dx,
        canvas_height: drag.tile.canvas_height + dy,
      })
    }
  }

  const onCanvasPointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    setDrag(null)
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  const beginZoneDrag = (
    event: React.PointerEvent<Element>,
    zone: FloorZone,
    kind: 'move-zone' | 'resize-zone',
  ) => {
    if (mode === 'live') return
    event.preventDefault()
    event.stopPropagation()
    setSelectedSharedZoneId(zone.id)
    setMapDrag({
      kind,
      zoneId: zone.id,
      pointer: mapPoint(event),
      zone,
    })
    mapCanvasRef.current?.setPointerCapture(event.pointerId)
  }

  const onMapPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!mapDrag) return
    const point = mapPoint(event)
    const dx = point.x - mapDrag.pointer.x
    const dy = point.y - mapDrag.pointer.y
    if (mapDrag.kind === 'move-zone') {
      updateFloorZone(mapDrag.zoneId, (zone) => moveZone(zone, dx, dy))
    } else {
      updateFloorZone(mapDrag.zoneId, (zone) => resizeZone(zone, dx, dy))
    }
  }

  const onMapPointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    setMapDrag(null)
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  if (mode === 'live') {
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={() => setMode('map')}
            className="rounded bg-teal-700 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-teal-600"
          >
            View 2D Store Map
          </button>
          <button
            onClick={enterEditMode}
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-500"
          >
            Edit Store Map
          </button>
          <button
            onClick={() => openCameraZoneEditor(cameras[0]?.id || '')}
            disabled={cameras.length === 0}
            className="rounded border border-gray-700 bg-gray-800 px-4 py-2 text-sm font-medium text-gray-100 transition-colors hover:bg-gray-700 disabled:opacity-50"
          >
            Edit Camera Zones
          </button>
          <span className="text-sm text-gray-500">The clean map is derived from the camera setup layer.</span>
        </div>
        <NormalCameraGrid cameras={cameras} onOpenCameraZoneEditor={openCameraZoneEditor} />
        {zoneEditorCamera && (
          <InlinePanel title={`Camera Zones: ${zoneEditorCamera.id}`} onClose={closeCameraZoneEditor}>
            <CameraSetup
              camera={zoneEditorCamera}
              storeName={storeName}
              onZoneChange={handleCameraZonesSaved}
              embedded
              onClose={closeCameraZoneEditor}
            />
          </InlinePanel>
        )}
      </div>
    )
  }

  if (mode === 'map') {
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-xs uppercase text-gray-500">{storeName}</p>
            <h2 className="mt-1 text-lg font-semibold">2D Store Map</h2>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setMode('live')}
              className="rounded bg-gray-800 px-4 py-2 text-sm font-medium text-gray-100 hover:bg-gray-700"
            >
              Live Cameras
            </button>
            <button
              onClick={enterEditMode}
              className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500"
            >
              Edit Store Map
            </button>
            <button
              onClick={addManualZone}
              className="rounded bg-teal-700 px-4 py-2 text-sm font-medium text-white hover:bg-teal-600"
            >
              Add Shared Zone
            </button>
            <button
              onClick={saveLayout}
              disabled={saving || !dirty}
              className="rounded bg-cyan-700 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-600 disabled:bg-gray-700"
            >
              {saving ? 'Saving...' : 'Save Layout'}
            </button>
          </div>
        </div>
        {status && <div className="rounded border border-teal-700 bg-teal-950/40 p-3 text-sm text-teal-100">{status}</div>}
        {error && <div className="rounded border border-red-700 bg-red-950/40 p-3 text-sm text-red-200">{error}</div>}
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_340px]">
          <CleanStoreMapEditor
            ref={mapCanvasRef}
            floorPlan={layout.floor_plan}
            zones={projectedZones}
            selectedZoneId={selectedSharedZoneId}
            onSelectZone={setSelectedSharedZoneId}
            onZonePointerDown={beginZoneDrag}
            onPointerMove={onMapPointerMove}
            onPointerUp={onMapPointerUp}
          />
          <SharedZoneInspector
            zone={selectedSharedZone}
            onAddZone={addManualZone}
            onDeleteZone={deleteSelectedZone}
            onSetMapTool={setMapTool}
            mapTool={mapTool}
            onUpdateZone={(patch) => {
              if (!selectedSharedZoneId) return
              updateFloorZone(selectedSharedZoneId, (zone) => applyZonePatch(zone, patch))
            }}
          />
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-xs uppercase text-gray-500">{storeName}</p>
          <h2 className="mt-1 text-lg font-semibold">Stage 1 Camera Arrangement</h2>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={extract2DMap} className="rounded bg-teal-700 px-4 py-2 text-sm font-medium text-white hover:bg-teal-600">
            Extract 2D Map
          </button>
          <button
            onClick={saveLayout}
            disabled={saving || !dirty}
            className="rounded bg-cyan-700 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-600 disabled:bg-gray-700"
          >
            {saving ? 'Saving...' : 'Save Layout'}
          </button>
          <button
            onClick={() => setMode('map')}
            className="rounded bg-gray-800 px-4 py-2 text-sm font-medium text-gray-100 hover:bg-gray-700"
          >
            View Clean Map
          </button>
          <button onClick={cancelEdit} className="rounded bg-gray-800 px-4 py-2 text-sm font-medium text-gray-100 hover:bg-gray-700">
            Cancel
          </button>
        </div>
      </div>

      {status && <div className="rounded border border-teal-700 bg-teal-950/40 p-3 text-sm text-teal-100">{status}</div>}
      {error && <div className="rounded border border-red-700 bg-red-950/40 p-3 text-sm text-red-200">{error}</div>}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_340px]">
        <div
          ref={canvasRef}
          onPointerMove={onCanvasPointerMove}
          onPointerUp={onCanvasPointerUp}
          onPointerCancel={onCanvasPointerUp}
          className="relative w-full touch-none overflow-hidden rounded border border-gray-800 bg-gray-900"
          style={{ aspectRatio: `${layout.floor_plan.canvas_width} / ${layout.floor_plan.canvas_height}` }}
        >
          <svg
            className="pointer-events-none absolute inset-0 h-full w-full"
            viewBox={`0 0 ${layout.floor_plan.canvas_width} ${layout.floor_plan.canvas_height}`}
            preserveAspectRatio="none"
          >
            {adjacency.map((edge) => {
              const a = layout.camera_arrangement.find((tile) => tile.camera_id === edge.camera_a_id)
              const b = layout.camera_arrangement.find((tile) => tile.camera_id === edge.camera_b_id)
              if (!a || !b) return null
              return (
                <line
                  key={pairKey(edge.camera_a_id, edge.camera_b_id)}
                  x1={a.canvas_x + a.canvas_width / 2}
                  y1={a.canvas_y + a.canvas_height / 2}
                  x2={b.canvas_x + b.canvas_width / 2}
                  y2={b.canvas_y + b.canvas_height / 2}
                  stroke="#94a3b8"
                  strokeDasharray="6 6"
                  strokeWidth="2"
                />
              )
            })}
            {projectedZones.map((zone) => {
              if (!zone.map_polygon.length) return null
              return (
                <polygon
                  key={zone.id}
                  points={zone.map_polygon.map((point) => point.join(',')).join(' ')}
                  fill="rgba(16,185,129,0.22)"
                  stroke="#34d399"
                  strokeWidth="2"
                />
              )
            })}
          </svg>

          {[...layout.camera_arrangement].sort((a, b) => a.z_index - b.z_index).map((tile) => {
            const camera = cameras.find((item) => item.id === tile.camera_id)
            return (
              <div
                key={tile.camera_id}
                role="button"
                tabIndex={0}
                onPointerDown={(event) => beginDrag(event, tile, 'move')}
                className={`absolute overflow-hidden rounded border bg-black ${
                  selectedCameraId === tile.camera_id ? 'border-cyan-300' : 'border-gray-700'
                }`}
                style={{
                  ...rectStyle(tile.canvas_x, tile.canvas_y, tile.canvas_width, tile.canvas_height, layout.floor_plan),
                  opacity: tile.opacity,
                  transform: `rotate(${tile.rotation_degrees}deg)`,
                  zIndex: tile.z_index,
                }}
              >
                <LiveFeed
                  cameraId={tile.camera_id}
                  className="h-full w-full object-cover"
                  onLoad={(width, height) => updateTile(tile.camera_id, {
                    source_frame_width: width,
                    source_frame_height: height,
                  }, false)}
                />
                {camera && tile.source_frame_width && tile.source_frame_height && (
                  <svg
                    className="pointer-events-none absolute inset-0 h-full w-full"
                    viewBox={`0 0 ${tile.source_frame_width} ${tile.source_frame_height}`}
                    preserveAspectRatio="none"
                  >
                    {camera.zones.map((zone) => (
                      <g key={zone.id}>
                        <polygon
                          points={zone.polygon.map((point) => point.join(',')).join(' ')}
                          fill={zone.promo_zone_flag ? 'rgba(234,179,8,0.22)' : 'rgba(20,184,166,0.18)'}
                          stroke={zone.promo_zone_flag ? '#facc15' : '#2dd4bf'}
                          strokeWidth="4"
                        />
                        <text
                          x={zone.polygon[0]?.[0] || 8}
                          y={(zone.polygon[0]?.[1] || 8) + 22}
                          fill="#f8fafc"
                          fontSize="22"
                          fontWeight="700"
                        >
                          {zone.name || zone.business_zone_type || zone.id}
                        </text>
                      </g>
                    ))}
                  </svg>
                )}
                <span className="absolute left-2 top-2 rounded bg-black/70 px-2 py-1 text-xs font-semibold text-white">
                  {tile.camera_id}
                </span>
                <span
                  onPointerDown={(event) => beginDrag(event, tile, 'resize')}
                  className="absolute bottom-0 right-0 h-5 w-5 cursor-nwse-resize border-l border-t border-cyan-300 bg-black/60"
                />
              </div>
            )
          })}
        </div>

        <aside className="space-y-4">
          {zoneEditorCamera && (
            <InlinePanel title={`Camera Zones: ${zoneEditorCamera.id}`} onClose={closeCameraZoneEditor}>
              <CameraSetup
                camera={zoneEditorCamera}
                storeName={storeName}
                onZoneChange={handleCameraZonesSaved}
                embedded
                onClose={closeCameraZoneEditor}
              />
            </InlinePanel>
          )}

          <section className="rounded border border-gray-800 bg-gray-950 p-4">
            <h3 className="mb-3 text-sm font-semibold">Store Scale</h3>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <NullableNumberField
                label="store_width_meters"
                value={layout.floor_plan.store_width_meters}
                onChange={(value) => updateFloorPlan({
                  store_width_meters: value,
                  scale_meters_per_pixel: value ? value / layout.floor_plan.canvas_width : null,
                })}
              />
              <NullableNumberField
                label="store_height_meters"
                value={layout.floor_plan.store_height_meters}
                onChange={(value) => updateFloorPlan({ store_height_meters: value })}
              />
              <NumberField
                label="canvas_width"
                value={layout.floor_plan.canvas_width}
                onChange={(value) => updateFloorPlan({
                  canvas_width: Math.max(300, value),
                  scale_meters_per_pixel: layout.floor_plan.store_width_meters
                    ? layout.floor_plan.store_width_meters / Math.max(300, value)
                    : null,
                })}
              />
              <NumberField
                label="canvas_height"
                value={layout.floor_plan.canvas_height}
                onChange={(value) => updateFloorPlan({ canvas_height: Math.max(300, value) })}
              />
              <p className="col-span-2 text-xs text-gray-500">
                Scale: {layout.floor_plan.scale_meters_per_pixel
                  ? `${layout.floor_plan.scale_meters_per_pixel.toFixed(4)} m/px`
                  : 'enter store width to compute scale'}
              </p>
            </div>
          </section>

          <section className="rounded border border-gray-800 bg-gray-950 p-4">
            <h3 className="mb-3 text-sm font-semibold">Overlap Confirmation</h3>
            <OverlapList
              candidates={overlapCandidates}
              onToggle={toggleOverlap}
            />
          </section>

          <section className="rounded border border-gray-800 bg-gray-950 p-4">
            <h3 className="mb-3 text-sm font-semibold">Clean Map Preview</h3>
            <div className="mb-3 flex flex-wrap gap-2">
              <button
                onClick={addManualZone}
                className="rounded bg-teal-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-teal-600"
              >
                Add Shared Zone
              </button>
              <button
                onClick={() => setMode('map')}
                className="rounded border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs font-medium text-gray-100 hover:bg-gray-700"
              >
                Open Map Editor
              </button>
            </div>
            <CleanStoreMapEditor
              ref={mapCanvasRef}
              floorPlan={layout.floor_plan}
              zones={projectedZones}
              compact
              selectedZoneId={selectedSharedZoneId}
              onSelectZone={setSelectedSharedZoneId}
              onZonePointerDown={beginZoneDrag}
              onPointerMove={onMapPointerMove}
              onPointerUp={onMapPointerUp}
            />
          </section>

          <section className="rounded border border-gray-800 bg-gray-950 p-4">
            <h3 className="mb-3 text-sm font-semibold">Selected Live Tile</h3>
            {selectedTile ? (
              <div className="grid grid-cols-2 gap-2 text-sm">
                {(['canvas_x', 'canvas_y', 'canvas_width', 'canvas_height', 'rotation_degrees', 'opacity', 'z_index'] as const).map((key) => (
                  <NumberField
                    key={key}
                    label={key}
                    value={selectedTile[key]}
                    onChange={(value) => updateTile(selectedTile.camera_id, { [key]: value })}
                  />
                ))}
                <button
                  onClick={() => openCameraZoneEditor(selectedTile.camera_id)}
                  className="col-span-2 rounded bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-500"
                >
                  Edit Camera Zones
                </button>
                <p className="col-span-2 text-xs text-gray-500">
                  Draw camera-local zones from Setup Zones. Extract 2D Map projects those zones from this live tile arrangement.
                </p>
              </div>
            ) : (
              <p className="text-sm text-gray-500">Select a live tile.</p>
            )}
          </section>

          <section className="rounded border border-gray-800 bg-gray-950 p-4">
            <h3 className="mb-3 text-sm font-semibold">Shared Zone Inspector</h3>
            <SharedZoneInspector
              zone={selectedSharedZone}
              onAddZone={addManualZone}
              onDeleteZone={deleteSelectedZone}
              onSetMapTool={setMapTool}
              mapTool={mapTool}
              onUpdateZone={(patch) => {
                if (!selectedSharedZoneId) return
                updateFloorZone(selectedSharedZoneId, (zone) => applyZonePatch(zone, patch))
              }}
            />
          </section>
        </aside>
      </div>
    </div>
  )

  function canvasPoint(event: React.PointerEvent<HTMLElement>): Point {
    const rect = canvasRef.current?.getBoundingClientRect()
    if (!rect) return { x: 0, y: 0 }
    return {
      x: clamp(((event.clientX - rect.left) / rect.width) * layout.floor_plan.canvas_width, 0, layout.floor_plan.canvas_width),
      y: clamp(((event.clientY - rect.top) / rect.height) * layout.floor_plan.canvas_height, 0, layout.floor_plan.canvas_height),
    }
  }

  function mapPoint(event: React.PointerEvent<Element>): Point {
    const rect = mapCanvasRef.current?.getBoundingClientRect()
    if (!rect) return { x: 0, y: 0 }
    return {
      x: clamp(((event.clientX - rect.left) / rect.width) * layout.floor_plan.canvas_width, 0, layout.floor_plan.canvas_width),
      y: clamp(((event.clientY - rect.top) / rect.height) * layout.floor_plan.canvas_height, 0, layout.floor_plan.canvas_height),
    }
  }
}

function NormalCameraGrid({
  cameras,
  onOpenCameraZoneEditor,
}: {
  cameras: CameraInfo[]
  onOpenCameraZoneEditor: (id: string) => void
}) {
  const gridCols =
    cameras.length === 1
      ? 'grid-cols-1'
      : cameras.length === 2
      ? 'grid-cols-1 lg:grid-cols-2'
      : cameras.length <= 4
      ? 'grid-cols-1 md:grid-cols-2'
      : 'grid-cols-1 md:grid-cols-2 xl:grid-cols-3'

  return (
    <div className={`grid ${gridCols} gap-4`}>
      {cameras.map((cam) => (
        <div key={cam.id} className="overflow-hidden rounded-lg border border-gray-800 bg-gray-900">
          <div className="flex items-center justify-between border-b border-gray-800 px-4 py-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold">{cam.id}</span>
              <span className="rounded-full bg-blue-900 px-2 py-0.5 text-xs text-blue-300">{cam.scene_type}</span>
              {cam.zones.length > 0 && (
                <span className="text-xs text-gray-500">
                  {cam.zones.length} zone{cam.zones.length !== 1 ? 's' : ''}
                </span>
              )}
            </div>
            <button
              onClick={() => onOpenCameraZoneEditor(cam.id)}
              className="rounded border border-gray-700 bg-gray-800 px-2.5 py-1 text-xs transition-colors hover:bg-gray-700"
            >
              Edit Zones
            </button>
          </div>
          <LiveFeed cameraId={cam.id} className="aspect-video w-full bg-black object-cover" />
        </div>
      ))}
    </div>
  )
}

const CleanStoreMapEditor = forwardRef<HTMLDivElement, {
  floorPlan: FloorPlanConfig
  zones: FloorZone[]
  selectedZoneId: string | null
  onSelectZone: (zoneId: string | null) => void
  onZonePointerDown: (event: React.PointerEvent<SVGElement | HTMLButtonElement>, zone: FloorZone, kind: 'move-zone' | 'resize-zone') => void
  onPointerMove: (event: React.PointerEvent<HTMLDivElement>) => void
  onPointerUp: (event: React.PointerEvent<HTMLDivElement>) => void
  compact?: boolean
}>(
  ({ floorPlan, zones, selectedZoneId, onSelectZone, onZonePointerDown, onPointerMove, onPointerUp, compact = false }, ref) => {
    return (
      <div
        ref={ref}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        className={`relative w-full overflow-hidden rounded border border-gray-800 bg-gray-900 ${compact ? '' : 'min-h-[420px]'}`}
        style={{ aspectRatio: `${floorPlan.canvas_width} / ${floorPlan.canvas_height}` }}
      >
        <svg
          className="absolute inset-0 h-full w-full"
          viewBox={`0 0 ${floorPlan.canvas_width} ${floorPlan.canvas_height}`}
          preserveAspectRatio="none"
        >
          <rect x="0" y="0" width={floorPlan.canvas_width} height={floorPlan.canvas_height} fill="#111827" />
          <path d={gridPath(floorPlan.canvas_width, floorPlan.canvas_height, 100)} stroke="#1f2937" strokeWidth="1" fill="none" />
          {zones.length === 0 && (
            <text x="40" y="60" fill="#64748b" fontSize={compact ? '28' : '34'}>
              Add or extract zones to edit the shared map
            </text>
          )}
          {zones.map((zone) => {
            const selected = zone.id === selectedZoneId
            const bounds = zoneBounds(zone)
            return (
              <g
                key={zone.id}
                onPointerDown={(event) => onZonePointerDown(event, zone, 'move-zone')}
                onClick={(event) => {
                  event.stopPropagation()
                  onSelectZone(zone.id)
                }}
                style={{ cursor: 'move' }}
              >
                {zone.map_polygon.length ? (
                  <polygon
                    points={zone.map_polygon.map((point) => point.join(',')).join(' ')}
                    fill={zone.promo_zone_flag ? 'rgba(234,179,8,0.30)' : 'rgba(20,184,166,0.26)'}
                    stroke={selected ? '#f8fafc' : zone.promo_zone_flag ? '#facc15' : '#2dd4bf'}
                    strokeWidth={selected ? (compact ? '4' : '5') : compact ? '3' : '4'}
                  />
                ) : (
                  <rect
                    x={zone.map_x}
                    y={zone.map_y}
                    width={zone.map_width}
                    height={zone.map_height}
                    fill="rgba(20,184,166,0.26)"
                    stroke={selected ? '#f8fafc' : '#2dd4bf'}
                    strokeWidth={selected ? (compact ? '4' : '5') : compact ? '3' : '4'}
                  />
                )}
                <text x={bounds.x + 8} y={bounds.y + 24} fill="#f8fafc" fontSize={compact ? '18' : '22'}>
                  {zone.zone_name}
                </text>
                {selected && (
                  <rect
                    x={bounds.x + bounds.width - 14}
                    y={bounds.y + bounds.height - 14}
                    width="14"
                    height="14"
                    fill="#f8fafc"
                    onPointerDown={(event) => onZonePointerDown(event, zone, 'resize-zone')}
                    style={{ cursor: 'nwse-resize' }}
                  />
                )}
              </g>
            )
          })}
        </svg>
      </div>
    )
  },
)

function SharedZoneInspector({
  zone,
  onAddZone,
  onDeleteZone,
  onSetMapTool,
  mapTool,
  onUpdateZone,
}: {
  zone: FloorZone | null
  onAddZone: () => void
  onDeleteZone: () => void
  onSetMapTool: (tool: MapTool) => void
  mapTool: MapTool
  onUpdateZone: (patch: Partial<FloorZone>) => void
}) {
  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap gap-2">
        <button onClick={onAddZone} className="rounded bg-teal-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-teal-600">
          Add Shared Zone
        </button>
        <button
          onClick={() => onSetMapTool(mapTool === 'add' ? 'select' : 'add')}
          className="rounded border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs font-medium text-gray-100 hover:bg-gray-700"
        >
          {mapTool === 'add' ? 'Select Zones' : 'Zone Tool'}
        </button>
        <button
          onClick={onDeleteZone}
          disabled={!zone}
          className="rounded border border-red-800 bg-red-950/30 px-3 py-1.5 text-xs font-medium text-red-200 hover:bg-red-950/50 disabled:opacity-50"
        >
          Delete
        </button>
      </div>
      {!zone ? (
        <p className="text-sm text-gray-500">Select a shared zone on the clean map to edit it.</p>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          <label className="col-span-2 text-gray-400">
            zone_name
            <input
              type="text"
              value={zone.zone_name}
              onChange={(event) => onUpdateZone({ zone_name: event.target.value })}
              className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-2 py-1 text-white"
            />
          </label>
          <label className="col-span-2 text-gray-400">
            zone_type
            <select
              value={zone.zone_type}
              onChange={(event) => onUpdateZone({ zone_type: event.target.value })}
              className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-2 py-1 text-white"
            >
              {['aisle', 'counter', 'checkout', 'entrance', 'promo', 'service_counter', 'staff', 'back_of_house'].map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </label>
          <label className="col-span-2 flex items-center gap-2 text-gray-300">
            <input
              type="checkbox"
              checked={zone.promo_zone_flag}
              onChange={(event) => onUpdateZone({ promo_zone_flag: event.target.checked })}
              className="h-4 w-4 rounded border-gray-700 bg-gray-800"
            />
            Promo zone
          </label>
          {(['map_x', 'map_y', 'map_width', 'map_height'] as const).map((key) => (
            <NumberField
              key={key}
              label={key}
              value={zone[key]}
              onChange={(value) => onUpdateZone({ [key]: value } as Partial<FloorZone>)}
            />
          ))}
          <p className="col-span-2 text-xs text-gray-500">
            Source: {zone.source_mode}
            {zone.source_camera_id && zone.source_zone_id ? ` from ${zone.source_camera_id}/${zone.source_zone_id}` : ''}
          </p>
        </div>
      )}
    </div>
  )
}

function InlinePanel({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: React.ReactNode
}) {
  return (
    <section className="rounded border border-gray-800 bg-gray-950 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold">{title}</h3>
        <button onClick={onClose} className="rounded border border-gray-700 bg-gray-800 px-2.5 py-1 text-xs text-gray-100 hover:bg-gray-700">
          Close
        </button>
      </div>
      {children}
    </section>
  )
}

function NumberField({
  label,
  value,
  onChange,
}: {
  label: string
  value: number
  onChange: (value: number) => void
}) {
  return (
    <label className="text-gray-400">
      {label}
      <input
        type="number"
        value={Number.isFinite(value) ? value : 0}
        onChange={(event) => onChange(Number(event.target.value) || 0)}
        className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-2 py-1 text-white"
      />
    </label>
  )
}

function NullableNumberField({
  label,
  value,
  onChange,
}: {
  label: string
  value: number | null
  onChange: (value: number | null) => void
}) {
  return (
    <label className="text-gray-400">
      {label}
      <input
        type="number"
        value={value ?? ''}
        placeholder="unset"
        onChange={(event) => {
          const nextValue = event.target.value.trim()
          onChange(nextValue === '' ? null : Number(nextValue))
        }}
        className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-2 py-1 text-white"
      />
    </label>
  )
}

function OverlapList({
  candidates,
  onToggle,
}: {
  candidates: CameraOverlap[]
  onToggle: (candidate: CameraOverlap, confirmed: boolean) => void
}) {
  if (candidates.length === 0) {
    return (
      <p className="text-sm text-gray-500">
        Drag tiles until overlapping camera views touch or overlap, then confirm pairs here.
      </p>
    )
  }

  return (
    <div className="space-y-2">
      {candidates.map((candidate) => (
        <label
          key={pairKey(candidate.camera_a_id, candidate.camera_b_id)}
          className="flex items-start gap-3 rounded border border-gray-800 bg-gray-900 p-2 text-sm"
        >
          <input
            type="checkbox"
            checked={candidate.confirmed_overlap}
            onChange={(event) => onToggle(candidate, event.target.checked)}
            className="mt-1 h-4 w-4 rounded border-gray-700 bg-gray-800"
          />
          <span>
            <span className="font-medium text-gray-100">
              {candidate.camera_a_id} <span className="text-gray-500">&lt;-&gt;</span> {candidate.camera_b_id}
            </span>
            <span className="block text-xs text-gray-500">
              Confirm only when these views share real store area or direct handoff coverage.
            </span>
          </span>
        </label>
      ))}
    </div>
  )
}

function normalizeLayout(data: Partial<SpatialConfig>, cameras: CameraInfo[]): SpatialConfig {
  const floorPlan = normalizeFloorPlan(data.floor_plan || DEFAULT_FLOOR_PLAN)
  const existing = new Map((data.camera_arrangement || []).map((tile) => [tile.camera_id, tile]))
  const cameraArrangement = cameras.map((camera, index) => {
    const saved = existing.get(camera.id)
    if (saved) {
      return withFloorPosition(clampTile(normalizeTile(saved, index), floorPlan), floorPlan)
    }
    return withFloorPosition({
      camera_id: camera.id,
      canvas_x: 40 + (index % 3) * 320,
      canvas_y: 40 + Math.floor(index / 3) * 220,
      canvas_width: 300,
      canvas_height: 180,
      floor_x: null,
      floor_y: null,
      position: '',
      coverage_area: camera.scene_type,
      rotation_degrees: 0,
      opacity: 1,
      z_index: index,
      source_frame_width: null,
      source_frame_height: null,
    }, floorPlan)
  })
  return {
    floor_plan: floorPlan,
    camera_arrangement: cameraArrangement,
    camera_adjacency: data.camera_adjacency || [],
    camera_overlaps: data.camera_overlaps || [],
    floor_zones: (data.floor_zones || []).map((zone) => normalizeZone(zone)),
  }
}

function normalizeFloorPlan(floorPlan: FloorPlanConfig): FloorPlanConfig {
  const canvasWidth = Math.max(300, Number(floorPlan.canvas_width) || DEFAULT_FLOOR_PLAN.canvas_width)
  const canvasHeight = Math.max(300, Number(floorPlan.canvas_height) || DEFAULT_FLOOR_PLAN.canvas_height)
  const storeWidthMeters = positiveOrNull(floorPlan.store_width_meters)
  return {
    ...floorPlan,
    canvas_width: canvasWidth,
    canvas_height: canvasHeight,
    store_width_meters: storeWidthMeters,
    store_height_meters: positiveOrNull(floorPlan.store_height_meters),
    scale_meters_per_pixel: storeWidthMeters ? storeWidthMeters / canvasWidth : null,
    origin: floorPlan.origin || 'bottom_left',
  }
}

function normalizeTile(tile: CameraArrangement, index: number): CameraArrangement {
  return {
    ...tile,
    rotation_degrees: tile.rotation_degrees ?? 0,
    opacity: tile.opacity ?? 1,
    z_index: tile.z_index ?? index,
    source_frame_width: tile.source_frame_width ?? null,
    source_frame_height: tile.source_frame_height ?? null,
  }
}

function normalizeZone(zone: FloorZone): FloorZone {
  return {
    ...zone,
    source_mode: zone.source_mode ?? (zone.source_camera_id ? 'projected' : 'manual'),
    source_camera_id: zone.source_camera_id ?? null,
    source_zone_id: zone.source_zone_id ?? null,
    map_polygon: zone.map_polygon ?? [],
  }
}

function projectZonesFromTiles(layout: SpatialConfig, cameras: CameraInfo[]): FloorZone[] {
  const zones: FloorZone[] = []
  for (const tile of layout.camera_arrangement) {
    const camera = cameras.find((item) => item.id === tile.camera_id)
    const sourceSize = camera ? inferSourceFrameSize(tile, camera) : null
    if (!camera || !sourceSize || camera.zones.length === 0) continue
    const tileWithSize = { ...tile, source_frame_width: sourceSize.width, source_frame_height: sourceSize.height }
    for (const zone of camera.zones) {
      const mapPolygon = zone.polygon.map((point) => projectCameraPointToMap(point[0], point[1], tileWithSize))
      const bounds = polygonBounds(mapPolygon)
      zones.push({
        id: `floor_zone_${tile.camera_id}_${zone.id}`,
        zone_name: zone.name || zone.id,
        zone_type: zone.business_zone_type || zone.type,
        source_mode: 'projected',
        promo_zone_flag: Boolean(zone.promo_zone_flag || zone.business_zone_type === 'promo'),
        map_x: bounds.x,
        map_y: bounds.y,
        map_width: bounds.width,
        map_height: bounds.height,
        source_camera_id: tile.camera_id,
        source_zone_id: zone.id,
        map_polygon: mapPolygon,
      })
    }
  }
  return zones
}

function reprojectFloorZones(zones: FloorZone[], tiles: CameraArrangement[], cameras: CameraInfo[]): FloorZone[] {
  return zones.map((zone) => {
    if (zone.source_mode !== 'projected' || !zone.source_camera_id || !zone.source_zone_id) return zone
    const tile = tiles.find((item) => item.camera_id === zone.source_camera_id)
    const camera = cameras.find((item) => item.id === zone.source_camera_id)
    const sourceZone = camera?.zones.find((item) => item.id === zone.source_zone_id)
    const sourceSize = tile && camera ? inferSourceFrameSize(tile, camera) : null
    if (!tile || !camera || !sourceZone || !sourceSize) return zone
    const tileWithSize = { ...tile, source_frame_width: sourceSize.width, source_frame_height: sourceSize.height }
    const mapPolygon = sourceZone.polygon.map((point) => projectCameraPointToMap(point[0], point[1], tileWithSize))
    const bounds = polygonBounds(mapPolygon)
    return {
      ...zone,
      zone_name: sourceZone.name || zone.zone_name,
      zone_type: sourceZone.business_zone_type || zone.zone_type,
      promo_zone_flag: Boolean(sourceZone.promo_zone_flag || sourceZone.business_zone_type === 'promo'),
      map_x: bounds.x,
      map_y: bounds.y,
      map_width: bounds.width,
      map_height: bounds.height,
      map_polygon: mapPolygon,
    }
  })
}

function inferSourceFrameSize(tile: CameraArrangement, camera: CameraInfo): { width: number; height: number } | null {
  if (tile.source_frame_width && tile.source_frame_height) {
    return { width: tile.source_frame_width, height: tile.source_frame_height }
  }
  let maxX = 0
  let maxY = 0
  for (const zone of camera.zones) {
    for (const point of zone.polygon) {
      maxX = Math.max(maxX, point[0])
      maxY = Math.max(maxY, point[1])
    }
  }
  return maxX > 0 && maxY > 0 ? { width: maxX, height: maxY } : null
}

function sourceZoneKey(sourceCameraId: string | null, sourceZoneId: string | null) {
  return `${sourceCameraId || ''}|${sourceZoneId || ''}`
}

function zoneBounds(zone: FloorZone) {
  if (zone.map_polygon.length > 0) {
    return polygonBounds(zone.map_polygon)
  }
  return { x: zone.map_x, y: zone.map_y, width: zone.map_width, height: zone.map_height }
}

function createRectZone({
  id,
  zone_name,
  zone_type,
  source_mode,
  promo_zone_flag,
  x,
  y,
  width,
  height,
}: {
  id: string
  zone_name: string
  zone_type: string
  source_mode: 'projected' | 'manual' | 'refined'
  promo_zone_flag: boolean
  x: number
  y: number
  width: number
  height: number
}): FloorZone {
  return {
    id,
    zone_name,
    zone_type,
    source_mode,
    promo_zone_flag,
    map_x: x,
    map_y: y,
    map_width: width,
    map_height: height,
    source_camera_id: null,
    source_zone_id: null,
    map_polygon: rectPolygon(x, y, width, height),
  }
}

function rectPolygon(x: number, y: number, width: number, height: number) {
  return [
    [x, y],
    [x + width, y],
    [x + width, y + height],
    [x, y + height],
  ]
}

function moveZone(zone: FloorZone, dx: number, dy: number): FloorZone {
  const bounds = zoneBounds(zone)
  return {
    ...zone,
    source_mode: zone.source_mode === 'projected' ? 'refined' : zone.source_mode,
    map_x: bounds.x + dx,
    map_y: bounds.y + dy,
    map_polygon: zone.map_polygon.length
      ? zone.map_polygon.map((point) => [point[0] + dx, point[1] + dy])
      : rectPolygon(bounds.x + dx, bounds.y + dy, bounds.width, bounds.height),
  }
}

function resizeZone(zone: FloorZone, dx: number, dy: number): FloorZone {
  const bounds = zoneBounds(zone)
  const nextWidth = Math.max(24, bounds.width + dx)
  const nextHeight = Math.max(24, bounds.height + dy)
  const scaleX = bounds.width > 0 ? nextWidth / bounds.width : 1
  const scaleY = bounds.height > 0 ? nextHeight / bounds.height : 1
  const polygon = zone.map_polygon.length
    ? zone.map_polygon.map((point) => [
        bounds.x + (point[0] - bounds.x) * scaleX,
        bounds.y + (point[1] - bounds.y) * scaleY,
      ])
    : rectPolygon(bounds.x, bounds.y, nextWidth, nextHeight)
  return {
    ...zone,
    source_mode: zone.source_mode === 'projected' ? 'refined' : zone.source_mode,
    map_x: bounds.x,
    map_y: bounds.y,
    map_width: nextWidth,
    map_height: nextHeight,
    map_polygon: polygon,
  }
}

function applyZonePatch(zone: FloorZone, patch: Partial<FloorZone>): FloorZone {
  const next = {
    ...zone,
    ...patch,
    source_mode:
      zone.source_mode === 'projected' &&
      (patch.map_x !== undefined ||
        patch.map_y !== undefined ||
        patch.map_width !== undefined ||
        patch.map_height !== undefined ||
        patch.map_polygon !== undefined)
        ? 'refined'
        : patch.source_mode ?? zone.source_mode,
  }
  const x = patch.map_x ?? next.map_x
  const y = patch.map_y ?? next.map_y
  const width = patch.map_width ?? next.map_width
  const height = patch.map_height ?? next.map_height
  if (!patch.map_polygon) {
    next.map_polygon = rectPolygon(x, y, width, height)
  }
  next.map_x = x
  next.map_y = y
  next.map_width = width
  next.map_height = height
  return next
}

function projectCameraPointToMap(sourceX: number, sourceY: number, tile: CameraArrangement): number[] {
  const sourceWidth = tile.source_frame_width || tile.canvas_width
  const sourceHeight = tile.source_frame_height || tile.canvas_height
  const localX = (sourceX / sourceWidth) * tile.canvas_width
  const localY = (sourceY / sourceHeight) * tile.canvas_height
  const centerX = tile.canvas_width / 2
  const centerY = tile.canvas_height / 2
  const radians = (tile.rotation_degrees * Math.PI) / 180
  const dx = localX - centerX
  const dy = localY - centerY
  return [
    tile.canvas_x + centerX + dx * Math.cos(radians) - dy * Math.sin(radians),
    tile.canvas_y + centerY + dx * Math.sin(radians) + dy * Math.cos(radians),
  ]
}

function deriveAdjacency(tiles: CameraArrangement[], scale: number): CameraAdjacency[] {
  const edges: CameraAdjacency[] = []
  for (let i = 0; i < tiles.length; i += 1) {
    for (let j = i + 1; j < tiles.length; j += 1) {
      const a = tiles[i]
      const b = tiles[j]
      const ac = center(a)
      const bc = center(b)
      const distance = Math.sqrt((ac.x - bc.x) ** 2 + (ac.y - bc.y) ** 2)
      const gap = rectGap(a, b)
      const threshold = Math.max(a.canvas_width, a.canvas_height, b.canvas_width, b.canvas_height) * 0.75
      if (intersectionArea(a, b) > 0 || gap <= threshold) {
        edges.push({
          camera_a_id: a.camera_id,
          camera_b_id: b.camera_id,
          edge_a: edgeFacing(ac.x, ac.y, bc.x, bc.y),
          edge_b: edgeFacing(bc.x, bc.y, ac.x, ac.y),
          distance_pixels: distance,
          distance_meters: scale ? distance * scale : null,
        })
      }
    }
  }
  return edges
}

function deriveOverlapCandidates(
  tiles: CameraArrangement[],
  confirmedOverlaps: CameraOverlap[],
): CameraOverlap[] {
  const confirmed = new Map(
    confirmedOverlaps
      .filter((overlap) => overlap.confirmed_overlap)
      .map((overlap) => [pairKey(overlap.camera_a_id, overlap.camera_b_id), overlap]),
  )
  const candidates: CameraOverlap[] = []

  for (let i = 0; i < tiles.length; i += 1) {
    for (let j = i + 1; j < tiles.length; j += 1) {
      const a = tiles[i]
      const b = tiles[j]
      const area = intersectionArea(a, b)
      const smallerTileArea = Math.min(a.canvas_width * a.canvas_height, b.canvas_width * b.canvas_height)
      const overlapRatio = smallerTileArea > 0 ? area / smallerTileArea : 0
      const key = pairKey(a.camera_id, b.camera_id)
      const saved = confirmed.get(key)

      if (!saved && overlapRatio < 0.03) continue

      candidates.push({
        camera_a_id: a.camera_id,
        camera_b_id: b.camera_id,
        confirmed_overlap: Boolean(saved),
        primary_camera_id: saved?.primary_camera_id || '',
      })
    }
  }

  return candidates.sort((a, b) => pairKey(a.camera_a_id, a.camera_b_id).localeCompare(pairKey(b.camera_a_id, b.camera_b_id)))
}

function withFloorPosition(tile: CameraArrangement, floorPlan: FloorPlanConfig): CameraArrangement {
  const scale = floorPlan.scale_meters_per_pixel
  if (!scale) return { ...tile, floor_x: null, floor_y: null }
  const centerX = tile.canvas_x + tile.canvas_width / 2
  const centerY = tile.canvas_y + tile.canvas_height / 2
  const floorY = floorPlan.origin === 'bottom_left'
    ? (floorPlan.canvas_height - centerY) * scale
    : centerY * scale
  return {
    ...tile,
    floor_x: centerX * scale,
    floor_y: floorY,
  }
}

function clampTile(tile: CameraArrangement, floorPlan: FloorPlanConfig): CameraArrangement {
  const width = clamp(tile.canvas_width, 80, floorPlan.canvas_width)
  const height = clamp(tile.canvas_height, 60, floorPlan.canvas_height)
  return {
    ...tile,
    canvas_width: width,
    canvas_height: height,
    canvas_x: clamp(tile.canvas_x, 0, floorPlan.canvas_width - width),
    canvas_y: clamp(tile.canvas_y, 0, floorPlan.canvas_height - height),
    opacity: clamp(tile.opacity, 0.2, 1),
  }
}

function clampZone(zone: FloorZone, floorPlan: FloorPlanConfig): FloorZone {
  return {
    ...zone,
    map_x: clamp(zone.map_x, 0, floorPlan.canvas_width),
    map_y: clamp(zone.map_y, 0, floorPlan.canvas_height),
    map_width: clamp(zone.map_width, 1, floorPlan.canvas_width),
    map_height: clamp(zone.map_height, 1, floorPlan.canvas_height),
  }
}

function rectStyle(x: number, y: number, width: number, height: number, floorPlan: FloorPlanConfig) {
  return {
    left: `${(x / floorPlan.canvas_width) * 100}%`,
    top: `${(y / floorPlan.canvas_height) * 100}%`,
    width: `${(width / floorPlan.canvas_width) * 100}%`,
    height: `${(height / floorPlan.canvas_height) * 100}%`,
  }
}

function center(tile: CameraArrangement): Point {
  return { x: tile.canvas_x + tile.canvas_width / 2, y: tile.canvas_y + tile.canvas_height / 2 }
}

function rectGap(a: CameraArrangement, b: CameraArrangement) {
  const dx = Math.max(a.canvas_x - (b.canvas_x + b.canvas_width), b.canvas_x - (a.canvas_x + a.canvas_width), 0)
  const dy = Math.max(a.canvas_y - (b.canvas_y + b.canvas_height), b.canvas_y - (a.canvas_y + a.canvas_height), 0)
  return Math.sqrt(dx * dx + dy * dy)
}

function intersectionArea(a: CameraArrangement, b: CameraArrangement) {
  const x = Math.max(0, Math.min(a.canvas_x + a.canvas_width, b.canvas_x + b.canvas_width) - Math.max(a.canvas_x, b.canvas_x))
  const y = Math.max(0, Math.min(a.canvas_y + a.canvas_height, b.canvas_y + b.canvas_height) - Math.max(a.canvas_y, b.canvas_y))
  return x * y
}

function edgeFacing(ax: number, ay: number, bx: number, by: number) {
  const dx = bx - ax
  const dy = by - ay
  return Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? 'right' : 'left') : (dy > 0 ? 'bottom' : 'top')
}

function polygonBounds(points: number[][]) {
  const xs = points.map((point) => point[0])
  const ys = points.map((point) => point[1])
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  return { x: minX, y: minY, width: Math.max(1, maxX - minX), height: Math.max(1, maxY - minY) }
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max)
}

function positiveOrNull(value: number | null | undefined) {
  return value && Number.isFinite(value) && value > 0 ? value : null
}

function pairKey(a: string, b: string) {
  return [a, b].sort().join('|')
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
