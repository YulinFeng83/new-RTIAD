/**
 * CameraSetup page — view annotated live feed and draw/manage zones.
 *
 * The MJPEG feed already has all overlays (bboxes, labels, stats HUD)
 * rendered by the Python backend. The ZoneDrawer canvas sits on top
 * of the feed so operators can draw polygon zones.
 */

import { useState, useEffect, useRef } from 'react'
import ZoneDrawer from '../components/ZoneDrawer'
import type { CameraInfo, ZoneInfo } from '../store-context'

interface CameraSetupProps {
  camera?: CameraInfo
  storeName: string
  onZoneChange: () => Promise<void>
  embedded?: boolean
  onClose?: () => void
}

export default function CameraSetup({
  camera,
  storeName,
  onZoneChange,
  embedded = false,
  onClose,
}: CameraSetupProps) {
  const [feedDimensions, setFeedDimensions] = useState({ width: 0, height: 0 })
  const [drawMode, setDrawMode] = useState(false)
  const [feedError, setFeedError] = useState(false)
  const imgRef = useRef<HTMLImageElement>(null)

  const cameraId = camera?.id || ''
  const zones = camera?.zones || []

  const API_BASE = import.meta.env.VITE_API_BASE || `http://${window.location.hostname}:8000`
  const feedUrl = `${API_BASE}/api/v1/cameras/${cameraId}/feed`

  useEffect(() => {
    setFeedError(false)
  }, [cameraId])

  const handleFeedLoad = () => {
    if (imgRef.current) {
      setFeedDimensions({
        width: imgRef.current.naturalWidth,
        height: imgRef.current.naturalHeight,
      })
    }
  }

  const handleZoneSaved = () => {
    void onZoneChange()
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

  const businessZoneLabel = (zoneType?: string) => {
    if (!zoneType) return 'aisle'
    return zoneType.replace(/_/g, ' ')
  }

  if (!camera) {
    return (
      <div className="rounded-lg border border-gray-800 bg-gray-900 p-6 text-sm text-gray-400">
        The selected camera is not available in the current store context.
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          {!embedded && <p className="text-xs uppercase tracking-[0.24em] text-gray-500">{storeName}</p>}
          <h2 className={`${embedded ? '' : 'mt-2'} text-lg font-semibold flex items-center gap-3`}>
            Camera: <span className="text-blue-400">{cameraId}</span>
          </h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
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
          {embedded && onClose && (
            <button
              onClick={onClose}
              className="px-4 py-2 rounded text-sm font-medium transition-colors bg-gray-800 hover:bg-gray-700 text-white"
            >
              Done
            </button>
          )}
        </div>
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
            key={feedUrl}
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
          existingZones={zones as ZoneInfo[]}
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
                <p className="mt-1 text-xs text-teal-300">
                  Layout: {businessZoneLabel(zone.business_zone_type)}
                  {zone.promo_zone_flag ? ' | Promo' : ''}
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
            Click <strong>"Draw Zones"</strong> to add entry, exit, aisle, counter, checkout, or restricted zones.
          </p>
        </div>
      )}
    </div>
  )
}
