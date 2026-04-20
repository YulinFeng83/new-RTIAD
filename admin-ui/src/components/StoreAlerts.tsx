export type StoreAlert = {
  id: string
  title: string
  detail: string
}

type StoreAlertsProps = {
  alerts: StoreAlert[]
}

export default function StoreAlerts({ alerts }: StoreAlertsProps) {
  return (
    <div className="rounded-2xl border border-gray-800 bg-gray-900/80 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white">Store alerts</h3>
        <span className="text-xs text-gray-500">{alerts.length} active</span>
      </div>
      {alerts.length === 0 ? (
        <p className="mt-3 text-sm text-gray-400">No current store-level alerts.</p>
      ) : (
        <div className="mt-3 space-y-3">
          {alerts.map((alert) => (
            <div key={alert.id} className="rounded-xl border border-amber-800/40 bg-amber-950/20 p-3">
              <p className="text-sm font-medium text-amber-200">{alert.title}</p>
              <p className="mt-1 text-sm text-amber-100/80">{alert.detail}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}