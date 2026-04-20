import StoreAlerts, { type StoreAlert } from './StoreAlerts'

export type StoreMetrics = {
  cameras: number
  zones: number
  occupancy: number | null
  entries: number | null
  exits: number | null
  indoorCount: number
  outdoorCount: number
}

type StoreOverviewProps = {
  storeName: string
  metrics: StoreMetrics
  alerts: StoreAlert[]
  hasScopedFootfall: boolean
}

export default function StoreOverview({
  storeName,
  metrics,
  alerts,
  hasScopedFootfall,
}: StoreOverviewProps) {
  return (
    <section className="space-y-4">
      <div className="rounded-2xl border border-gray-800 bg-gradient-to-br from-gray-900 via-gray-900 to-gray-950 p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.28em] text-gray-500">Store dashboard</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-white">{storeName}</h2>
            <p className="mt-2 max-w-2xl text-sm text-gray-400">
              Switch the active store to scope cameras, zones, dashboard metrics, and setup actions to a single store context.
            </p>
          </div>
          {!hasScopedFootfall && (
            <div className="rounded-full border border-amber-700/50 bg-amber-950/40 px-3 py-1 text-xs text-amber-300">
              Footfall stays store-global until backend APIs return scoped stats.
            </div>
          )}
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <MetricCard label="Live cameras" value={metrics.cameras.toString()} hint={`${metrics.indoorCount} indoor / ${metrics.outdoorCount} outdoor`} />
        <MetricCard label="Configured zones" value={metrics.zones.toString()} hint="Visible camera zones only" />
        <MetricCard label="Current occupancy" value={metrics.occupancy === null ? 'N/A' : metrics.occupancy.toString()} hint="Scoped to active store when available" />
        <MetricCard label="Entries" value={metrics.entries === null ? 'N/A' : metrics.entries.toString()} hint="Current runtime total" />
        <MetricCard label="Exits" value={metrics.exits === null ? 'N/A' : metrics.exits.toString()} hint="Current runtime total" />
      </div>

      <StoreAlerts alerts={alerts} />
    </section>
  )
}

function MetricCard({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-2xl border border-gray-800 bg-gray-900/80 p-4">
      <p className="text-xs uppercase tracking-[0.24em] text-gray-500">{label}</p>
      <p className="mt-3 text-3xl font-semibold tracking-tight text-white">{value}</p>
      <p className="mt-2 text-sm text-gray-400">{hint}</p>
    </div>
  )
}