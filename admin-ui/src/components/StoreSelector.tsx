type StoreOption = {
  id: string
  name: string
}

type StoreSelectorProps = {
  stores: StoreOption[]
  selectedStoreId: string
  cameraCount: number
  onChange: (storeId: string) => void
  onRefresh: () => void
}

export default function StoreSelector({
  stores,
  selectedStoreId,
  cameraCount,
  onChange,
  onRefresh,
}: StoreSelectorProps) {
  return (
    <div className="flex items-center gap-3">
      <label className="flex items-center gap-2 text-sm text-gray-400">
        <span>Store</span>
        <select
          value={selectedStoreId}
          onChange={(event) => onChange(event.target.value)}
          className="rounded border border-gray-700 bg-gray-900 px-3 py-1.5 text-sm text-white outline-none"
        >
          {stores.map((store) => (
            <option key={store.id} value={store.id}>
              {store.name}
            </option>
          ))}
        </select>
      </label>
      <span className="text-xs text-gray-500">
        {cameraCount} camera{cameraCount !== 1 ? 's' : ''}
      </span>
      <button
        onClick={onRefresh}
        className="text-sm bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded px-3 py-1.5 transition-colors"
      >
        Refresh
      </button>
    </div>
  )
}