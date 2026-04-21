import type { ReactNode } from 'react'

interface Point {
  x: number
  y: number
}

export default function CalibrationPointCanvas({
  width,
  height,
  points,
  ghostPoints = [],
  onAddPoint,
  children,
  title,
  subtitle,
  disabled = false,
}: {
  width: number
  height: number
  points: Point[]
  ghostPoints?: Point[]
  onAddPoint?: (point: Point) => void
  children: ReactNode
  title: string
  subtitle?: string
  disabled?: boolean
}) {
  const handleClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!onAddPoint || disabled || width <= 0 || height <= 0) return
    const rect = event.currentTarget.getBoundingClientRect()
    const x = ((event.clientX - rect.left) / rect.width) * width
    const y = ((event.clientY - rect.top) / rect.height) * height
    onAddPoint({
      x: clamp(x, 0, width),
      y: clamp(y, 0, height),
    })
  }

  return (
    <section className="rounded border border-gray-800 bg-gray-900 p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-100">{title}</h3>
          {subtitle && <p className="mt-1 text-xs text-gray-500">{subtitle}</p>}
        </div>
        <span className="rounded bg-gray-800 px-2 py-1 text-xs text-gray-300">
          {width > 0 && height > 0 ? `${Math.round(width)} x ${Math.round(height)}` : 'Waiting for dimensions'}
        </span>
      </div>

      <div
        onClick={handleClick}
        className={`relative overflow-hidden rounded border border-gray-800 bg-gray-950 ${
          disabled ? 'cursor-not-allowed opacity-80' : 'cursor-crosshair'
        }`}
        style={{ aspectRatio: width > 0 && height > 0 ? `${width} / ${height}` : '16 / 9' }}
      >
        {children}

        <div className="pointer-events-none absolute inset-0">
          {ghostPoints.map((point, index) => (
            <Marker
              key={`ghost-${index + 1}`}
              x={point.x}
              y={point.y}
              width={width}
              height={height}
              label={index + 1}
              ghost
            />
          ))}
          {points.map((point, index) => (
            <Marker
              key={`point-${index + 1}`}
              x={point.x}
              y={point.y}
              width={width}
              height={height}
              label={index + 1}
            />
          ))}
        </div>
      </div>
    </section>
  )
}

function Marker({
  x,
  y,
  width,
  height,
  label,
  ghost = false,
}: {
  x: number
  y: number
  width: number
  height: number
  label: number
  ghost?: boolean
}) {
  if (width <= 0 || height <= 0) return null
  return (
    <div
      className="absolute -translate-x-1/2 -translate-y-1/2"
      style={{
        left: `${(x / width) * 100}%`,
        top: `${(y / height) * 100}%`,
      }}
    >
      <div
        className={`flex h-6 w-6 items-center justify-center rounded-full border text-[11px] font-semibold ${
          ghost
            ? 'border-amber-300 bg-amber-500/25 text-amber-100'
            : 'border-cyan-200 bg-cyan-500/90 text-gray-950'
        }`}
      >
        {label}
      </div>
    </div>
  )
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max)
}
