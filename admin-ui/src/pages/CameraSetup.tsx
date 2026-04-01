/**
 * CameraSetup page — view annotated live feed and draw/manage zones.
 *
 * The MJPEG feed already has all overlays (bboxes, labels, stats HUD)
 * rendered by the Python backend. The ZoneDrawer canvas sits on top
 * of the feed so operators can draw polygon zones.
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import ZoneDrawer from '../components/ZoneDrawer'

interface CameraSetupProps {
  cameraId: string
  onZoneChange: () => void
}

interface ZoneData {
  id: string
  camera_id: string
  type: string
  polygon: number[][]
  direction: number[]
  name: string
}

export default function CameraSetup({ cameraId, onZoneChange }: CameraSetupProps) {
  const [feedDimensions, setFeedDimensions] = useState({ width: 0, height: 0 })
  const [zones, setZones] = useState<ZoneData[]>([])
  const [drawMode, setDrawMode] = useState(false)
  const [feedError, setFeedError] = useState(false)
  const imgRef = useRef<HTMLImageElement>(null)

  const feedUrl = `/api/v1/cameras/${cameraId}/feed`

  const fetchZones = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/cameras')
      const cameras = await res.json()
      const cam = cameras.find((c: any) => c.id === cameraId)
      if (cam) {
        setZones(cam.zones)
      }
    } catch (err) {
      console.error('Failed to fetch zones:', err)
    }
  }, [cameraId])

  useEffect(() => {
    fetchZones()
    setFeedError(false)
  }, [fetchZones])

  const handleFeedLoad = () => {
    if (imgRef.current) {
      setFeedDimensions({
        width: imgRef.current.naturalWidth,
        height: imgRef.current.naturalHeight,
      })
    }
  }

  const handleZoneSaved = () => {
    fetchZones()
    onZoneChange()
  }

  const zoneColor = (zoneType: string) => {
    if (zoneType === 'entry') return '#00c800'
    if (zoneType === 'exit') return '#c80000'
    if (zoneType === 'staff_only') return '#ff8c00'
    return '#c8c800'
  }

  const zoneTypeLabel = (zoneType: string) => {
    if (zoneType === 'staff_only') return 'restricted / staff only'
    return zoneType
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold flex items-center gap-3">
          Camera: <span className="text-blue-400">{cameraId}</span>
        </h2>
        <button
          onClick={() => setDrawMode(!drawMode)}
          className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
            drawMode
              ? 'bg-yellow-600 hover:bg-yellow-500 text-white'
              : 'bg-blue-600 hover:bg-blue-500 text-white'
          }`}
        >
          {drawMode ? 'Exit Zone Drawing' : 'Draw Zones'}
        </button>
      </div>

      {/* Feed + zone canvas in same relative container */}
      <div className="relative inline-block max-w-full">
        {feedError ? (
          <div className="flex items-center justify-center bg-gray-900 rounded-lg min-h-[300px] w-[640px]">
            <div className="text-center text-gray-500">
              <p className="text-lg">No feed available</p>
              <p className="text-sm mt-1">Camera: {cameraId}</p>
              <button
                onClick={() => setFeedError(false)}
                className="mt-3 text-sm text-blue-400 hover:text-blue-300"
              >
                Retry
              </button>
            </div>
          </div>
        ) : (
          <img
            ref={imgRef}
            src={feedUrl}
            alt={`Live feed: ${cameraId}`}
            className="max-w-full max-h-[75vh] rounded-lg block"
            onLoad={handleFeedLoad}
            onError={() => setFeedError(true)}
          />
        )}

        {drawMode && feedDimensions.width > 0 && !feedError && (
          <canvas
            id="zone-canvas"
            width={feedDimensions.width}
            height={feedDimensions.height}
            className="absolute top-0 left-0 w-full h-full cursor-crosshair rounded-lg"
            style={{ zIndex: 10 }}
          />
        )}
      </div>

      {drawMode && feedDimensions.width > 0 && (
        <ZoneDrawer
          cameraId={cameraId}
          canvasId="zone-canvas"
          feedWidth={feedDimensions.width}
          feedHeight={feedDimensions.height}
          existingZones={zones}
          onZoneSaved={handleZoneSaved}
        />
      )}

      {/* Zones list when not in draw mode */}
      {!drawMode && zones.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-300 mb-2">Configured Zones</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {zones.map((zone) => (
              <div
                key={zone.id}
                className="bg-gray-900 border border-gray-800 rounded-lg p-3"
              >
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className="w-2.5 h-2.5 rounded-full"
                    style={{ backgroundColor: zoneColor(zone.type) }}
                  />
                  <span className="font-medium text-sm">{zone.name || zone.id}</span>
                </div>
                <p className="text-xs text-gray-500">
                  Type: {zoneTypeLabel(zone.type)} | Points: {zone.polygon.length}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {!drawMode && zones.length === 0 && (
        <div className="text-center text-gray-500 py-8 border border-dashed border-gray-800 rounded-lg">
          <p>No zones configured for this camera.</p>
          <p className="text-sm mt-1">
            Click <strong>"Draw Zones"</strong> to add entry, exit, bidirectional, or restricted zones.
          </p>
        </div>
      )}
    </div>
  )
}
