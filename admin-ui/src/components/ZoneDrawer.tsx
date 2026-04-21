/**
 * ZoneDrawer — controls for drawing polygon zones on a canvas that is
 * overlaid on the camera feed by the parent component.
 *
 * Flow:
 *   1. Click to place polygon vertices on the video
 *   2. Double-click to close the polygon
 *   3. Click on the "INSIDE the store" side of the zone to set direction
 *      (the arrow points from the zone center toward where you clicked)
 *   4. Pick zone type, name, and save
 */

import { useRef, useState, useEffect, useCallback } from 'react'

interface Point {
  x: number
  y: number
}

interface ZoneData {
  id: string
  camera_id: string
  type: string
  business_zone_type?: string
  polygon: number[][]
  direction: number[]
  name: string
  promo_zone_flag?: boolean
}

interface ZoneDrawerProps {
  cameraId: string
  canvasId: string
  feedWidth: number
  feedHeight: number
  existingZones: ZoneData[]
  onZoneSaved: () => void
}

const ZONE_COLORS: Record<string, string> = {
  entry: 'rgba(0, 200, 0, 0.4)',
  exit: 'rgba(200, 0, 0, 0.4)',
  bidirectional: 'rgba(200, 200, 0, 0.4)',
  staff_only: 'rgba(255, 140, 0, 0.4)',
}

const ZONE_BORDER_COLORS: Record<string, string> = {
  entry: '#00c800',
  exit: '#c80000',
  bidirectional: '#c8c800',
  staff_only: '#ff8c00',
}

const ZONE_TYPE_LABELS: Record<string, string> = {
  entry: 'Entry',
  exit: 'Exit',
  bidirectional: 'Bidirectional',
  staff_only: 'Restricted / Staff Only',
}

const BUSINESS_ZONE_TYPES = [
  { value: 'aisle', label: 'Aisle' },
  { value: 'counter', label: 'Counter' },
  { value: 'checkout', label: 'Checkout' },
  { value: 'entrance', label: 'Entrance' },
  { value: 'promo', label: 'Promo Area' },
  { value: 'service_counter', label: 'Service Counter' },
  { value: 'staff', label: 'Staff Area' },
  { value: 'back_of_house', label: 'Back of House' },
]

const BUSINESS_ZONE_LABELS = Object.fromEntries(
  BUSINESS_ZONE_TYPES.map((item) => [item.value, item.label])
)

type DrawPhase = 'drawing' | 'set_direction' | 'ready'

export default function ZoneDrawer({
  cameraId,
  canvasId,
  feedWidth,
  feedHeight,
  existingZones,
  onZoneSaved,
}: ZoneDrawerProps) {
  const [points, setPoints] = useState<Point[]>([])
  const [phase, setPhase] = useState<DrawPhase>('drawing')
  const [zoneType, setZoneType] = useState<string>('bidirectional')
  const [businessZoneType, setBusinessZoneType] = useState<string>('aisle')
  const [zoneName, setZoneName] = useState('')
  const [promoZoneFlag, setPromoZoneFlag] = useState(false)
  const [mousePos, setMousePos] = useState<Point | null>(null)
  const [direction, setDirection] = useState<[number, number]>([0, -1])

  const pointsRef = useRef(points)
  const phaseRef = useRef(phase)
  pointsRef.current = points
  phaseRef.current = phase

  const getPolygonCenter = useCallback((): Point => {
    const pts = pointsRef.current
    if (pts.length === 0) return { x: 0, y: 0 }
    const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length
    const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length
    return { x: cx, y: cy }
  }, [])

  const getCanvasPoint = useCallback(
    (e: MouseEvent): Point => {
      const canvas = document.getElementById(canvasId) as HTMLCanvasElement
      if (!canvas) return { x: 0, y: 0 }
      const rect = canvas.getBoundingClientRect()
      const scaleX = feedWidth / rect.width
      const scaleY = feedHeight / rect.height
      return {
        x: Math.round((e.clientX - rect.left) * scaleX),
        y: Math.round((e.clientY - rect.top) * scaleY),
      }
    },
    [canvasId, feedWidth, feedHeight]
  )

  useEffect(() => {
    const canvas = document.getElementById(canvasId) as HTMLCanvasElement
    if (!canvas) return

    const handleClick = (e: MouseEvent) => {
      const pt = getCanvasPoint(e)

      if (phaseRef.current === 'set_direction') {
        const center = getPolygonCenter()
        const dx = pt.x - center.x
        const dy = pt.y - center.y
        const mag = Math.sqrt(dx * dx + dy * dy)
        if (mag > 0) {
          setDirection([dx / mag, dy / mag])
        }
        setPhase('ready')
        return
      }

      if (phaseRef.current === 'drawing') {
        setPoints((prev) => [...prev, pt])
      }
    }

    const handleDblClick = (e: MouseEvent) => {
      e.preventDefault()
      if (phaseRef.current === 'drawing' && pointsRef.current.length >= 3) {
        setPhase('set_direction')
      }
    }

    const handleMouseMove = (e: MouseEvent) => {
      setMousePos(getCanvasPoint(e))
    }

    canvas.addEventListener('click', handleClick)
    canvas.addEventListener('dblclick', handleDblClick)
    canvas.addEventListener('mousemove', handleMouseMove)

    return () => {
      canvas.removeEventListener('click', handleClick)
      canvas.removeEventListener('dblclick', handleDblClick)
      canvas.removeEventListener('mousemove', handleMouseMove)
    }
  }, [canvasId, getCanvasPoint, getPolygonCenter])

  // Render onto the canvas
  useEffect(() => {
    const canvas = document.getElementById(canvasId) as HTMLCanvasElement
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    ctx.clearRect(0, 0, canvas.width, canvas.height)

    // Draw existing zones
    for (const zone of existingZones) {
      drawZone(ctx, zone)
    }

    if (points.length === 0) return

    // Draw current polygon
    ctx.beginPath()
    ctx.moveTo(points[0].x, points[0].y)
    for (let i = 1; i < points.length; i++) {
      ctx.lineTo(points[i].x, points[i].y)
    }

    if (phase !== 'drawing') {
      ctx.closePath()
      ctx.fillStyle = 'rgba(100, 150, 255, 0.25)'
      ctx.fill()
    } else if (mousePos) {
      ctx.lineTo(mousePos.x, mousePos.y)
    }
    ctx.strokeStyle = '#6496ff'
    ctx.lineWidth = 2
    ctx.stroke()

    // Vertices
    for (const pt of points) {
      ctx.beginPath()
      ctx.arc(pt.x, pt.y, 5, 0, Math.PI * 2)
      ctx.fillStyle = '#fff'
      ctx.fill()
      ctx.strokeStyle = '#6496ff'
      ctx.lineWidth = 2
      ctx.stroke()
    }

    const center = getPolygonCenter()

    // Direction-setting phase: show live IN arrow + opposite OUT arrow
    if (phase === 'set_direction' && mousePos) {
      const dx = mousePos.x - center.x
      const dy = mousePos.y - center.y
      const mag = Math.sqrt(dx * dx + dy * dy)
      const arrowLen = 50

      if (mag > 5) {
        const nx = dx / mag
        const ny = dy / mag

        // IN arrow (green) — toward mouse
        const inX = center.x + nx * arrowLen
        const inY = center.y + ny * arrowLen
        drawArrow(ctx, center.x, center.y, inX, inY, '#00ff88')
        ctx.fillStyle = '#00ff88'
        ctx.font = 'bold 16px sans-serif'
        ctx.textAlign = 'center'
        ctx.fillText('IN', inX + nx * 18, inY + ny * 18)

        // OUT arrow (red) — exact opposite direction
        const outX = center.x - nx * arrowLen
        const outY = center.y - ny * arrowLen
        drawArrow(ctx, center.x, center.y, outX, outY, '#ff6464')
        ctx.fillStyle = '#ff6464'
        ctx.font = 'bold 16px sans-serif'
        ctx.textAlign = 'center'
        ctx.fillText('OUT', outX - nx * 18, outY - ny * 18)
      }

      ctx.fillStyle = '#ffffff'
      ctx.font = 'bold 13px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText('Click the INSIDE (store) side', center.x, center.y - 15)
    }

    // Ready phase: show final IN + OUT arrows (exact opposites)
    if (phase === 'ready') {
      const arrowLen = 50

      // IN arrow (green)
      const inX = center.x + direction[0] * arrowLen
      const inY = center.y + direction[1] * arrowLen
      drawArrow(ctx, center.x, center.y, inX, inY, '#00ff88')
      ctx.fillStyle = '#00ff88'
      ctx.font = 'bold 16px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText('IN', inX + direction[0] * 18, inY + direction[1] * 18)

      // OUT arrow (red) — exact opposite
      const outX = center.x - direction[0] * arrowLen
      const outY = center.y - direction[1] * arrowLen
      drawArrow(ctx, center.x, center.y, outX, outY, '#ff6464')
      ctx.fillStyle = '#ff6464'
      ctx.font = 'bold 16px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText('OUT', outX - direction[0] * 18, outY - direction[1] * 18)
    }
  }, [canvasId, points, existingZones, mousePos, phase, direction, getPolygonCenter])

  const handleSave = async () => {
    if (points.length < 3) return

    const zoneId = `zone_${Date.now()}`
    const payload = {
      id: zoneId,
      type: zoneType,
      business_zone_type: businessZoneType,
      polygon: points.map((p) => [p.x, p.y]),
      direction: direction,
      name: zoneName || zoneId,
      promo_zone_flag: promoZoneFlag || businessZoneType === 'promo',
    }

    try {
      const res = await fetch(`/api/v1/cameras/${cameraId}/zones`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (res.ok) {
        resetDrawing()
        onZoneSaved()
      } else {
        console.error('Failed to save zone:', await res.text())
      }
    } catch (err) {
      console.error('Failed to save zone:', err)
    }
  }

  const handleDeleteZone = async (zoneId: string) => {
    try {
      await fetch(`/api/v1/cameras/${cameraId}/zones/${zoneId}`, {
        method: 'DELETE',
      })
      onZoneSaved()
    } catch (err) {
      console.error('Failed to delete zone:', err)
    }
  }

  const resetDrawing = () => {
    setPoints([])
    setPhase('drawing')
    setZoneName('')
    setBusinessZoneType('aisle')
    setPromoZoneFlag(false)
    setDirection([0, -1])
  }

  const statusText =
    phase === 'set_direction'
      ? 'Now click on the INSIDE (store) side of the zone to set the "entering" direction'
      : phase === 'ready'
      ? 'Direction set! Choose zone type, give it a name, and click Save'
      : points.length === 0
      ? 'Click on the video to start drawing a zone polygon'
      : `Drawing... (${points.length} points) — double-click to close polygon`

  const statusColor =
    phase === 'set_direction'
      ? 'bg-red-400 animate-pulse'
      : phase === 'ready'
      ? 'bg-green-400'
      : points.length > 0
      ? 'bg-yellow-400 animate-pulse'
      : 'bg-gray-500'

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className={`w-2 h-2 rounded-full ${statusColor}`} />
        <p className="text-sm text-gray-400">{statusText}</p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <select
          value={zoneType}
          onChange={(e) => setZoneType(e.target.value)}
          className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm"
          title="Runtime crossing behavior"
        >
          <option value="entry">Entry</option>
          <option value="exit">Exit</option>
          <option value="bidirectional">Bidirectional</option>
          <option value="staff_only">Restricted / Staff Only</option>
        </select>

        <select
          value={businessZoneType}
          onChange={(e) => setBusinessZoneType(e.target.value)}
          className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm"
          title="Business layout zone"
        >
          {BUSINESS_ZONE_TYPES.map((zone) => (
            <option key={zone.value} value={zone.value}>
              {zone.label}
            </option>
          ))}
        </select>

        <input
          type="text"
          placeholder="Zone name, e.g. Cereal aisle"
          value={zoneName}
          onChange={(e) => setZoneName(e.target.value)}
          className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm w-40"
        />

        <label className="flex items-center gap-2 text-sm text-gray-300">
          <input
            type="checkbox"
            checked={promoZoneFlag}
            onChange={(e) => setPromoZoneFlag(e.target.checked)}
            className="h-4 w-4 rounded border-gray-700 bg-gray-800"
          />
          Promo zone
        </label>

        <button
          onClick={handleSave}
          disabled={phase !== 'ready'}
          className="bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded px-4 py-1.5 text-sm transition-colors"
        >
          Save Zone
        </button>

        <button
          onClick={resetDrawing}
          className="bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded px-4 py-1.5 text-sm transition-colors"
        >
          Clear
        </button>
      </div>

      {existingZones.length > 0 && (
        <div className="mt-4">
          <h3 className="text-sm font-semibold text-gray-300 mb-2">Existing Zones</h3>
          <div className="space-y-2">
            {existingZones.map((zone) => (
              <div
                key={zone.id}
                className="flex items-center justify-between bg-gray-900 border border-gray-800 rounded px-3 py-2"
              >
                <div className="flex items-center gap-3">
                  <span
                    className="w-3 h-3 rounded-full"
                    style={{ backgroundColor: ZONE_BORDER_COLORS[zone.type] || '#888' }}
                  />
                  <span className="text-sm">{zone.name || zone.id}</span>
                  <span className="text-xs text-gray-500">{ZONE_TYPE_LABELS[zone.type] || zone.type}</span>
                  <span className="text-xs text-teal-300">
                    {BUSINESS_ZONE_LABELS[zone.business_zone_type || 'aisle'] || zone.business_zone_type || 'Aisle'}
                  </span>
                  {zone.promo_zone_flag && <span className="text-xs text-yellow-300">Promo</span>}
                </div>
                <button
                  onClick={() => handleDeleteZone(zone.id)}
                  className="text-red-400 hover:text-red-300 text-sm"
                >
                  Delete
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function drawZone(ctx: CanvasRenderingContext2D, zone: ZoneData) {
  const pts = zone.polygon
  if (pts.length < 3) return

  ctx.beginPath()
  ctx.moveTo(pts[0][0], pts[0][1])
  for (let i = 1; i < pts.length; i++) {
    ctx.lineTo(pts[i][0], pts[i][1])
  }
  ctx.closePath()
  ctx.fillStyle = ZONE_COLORS[zone.type] || ZONE_COLORS.bidirectional
  ctx.fill()
  ctx.strokeStyle = ZONE_BORDER_COLORS[zone.type] || ZONE_BORDER_COLORS.bidirectional
  ctx.lineWidth = 2
  ctx.stroke()

  const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length
  const cy = pts.reduce((s, p) => s + p[1], 0) / pts.length
  ctx.fillStyle = '#fff'
  ctx.font = '14px monospace'
  ctx.textAlign = 'center'
  ctx.fillText(zone.name || zone.id, cx, cy - 8)

  if (zone.direction && zone.direction.length >= 2) {
    const arrowLen = 35
    const dx = zone.direction[0]
    const dy = zone.direction[1]

    // IN arrow (green)
    const inX = cx + dx * arrowLen
    const inY = cy + dy * arrowLen
    drawArrow(ctx, cx, cy, inX, inY, '#00ff88')
    ctx.fillStyle = '#00ff88'
    ctx.font = 'bold 12px sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText('IN', inX + dx * 14, inY + dy * 14)

    // OUT arrow (red) — exact opposite
    const outX = cx - dx * arrowLen
    const outY = cy - dy * arrowLen
    drawArrow(ctx, cx, cy, outX, outY, '#ff6464')
    ctx.fillStyle = '#ff6464'
    ctx.font = 'bold 12px sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText('OUT', outX - dx * 14, outY - dy * 14)
  }
}

function drawArrow(
  ctx: CanvasRenderingContext2D,
  fromX: number,
  fromY: number,
  toX: number,
  toY: number,
  color: string
) {
  const headLen = 12
  const angle = Math.atan2(toY - fromY, toX - fromX)

  ctx.beginPath()
  ctx.moveTo(fromX, fromY)
  ctx.lineTo(toX, toY)
  ctx.strokeStyle = color
  ctx.lineWidth = 2
  ctx.stroke()

  ctx.beginPath()
  ctx.moveTo(toX, toY)
  ctx.lineTo(
    toX - headLen * Math.cos(angle - Math.PI / 6),
    toY - headLen * Math.sin(angle - Math.PI / 6)
  )
  ctx.lineTo(
    toX - headLen * Math.cos(angle + Math.PI / 6),
    toY - headLen * Math.sin(angle + Math.PI / 6)
  )
  ctx.closePath()
  ctx.fillStyle = color
  ctx.fill()
}
