import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react'

export interface ZoneInfo {
  id: string
  camera_id: string
  type: string
  polygon: number[][]
  direction: number[]
  name: string
}

export interface CameraInfo {
  id: string
  url: string
  scene_type: string
  zones: ZoneInfo[]
  store_id?: string
  store_name?: string
}

export interface FootfallStats {
  store_id?: string | null
  total_entries: number
  total_exits: number
  current_in_store: number
  employees_filtered: number
  total_group_entries: number
  total_group_exits: number
  current_groups_in_store: number
}

interface ConfigResponse {
  store?: {
    store_id?: string
    name?: string
  }
}

interface StoreOption {
  id: string
  name: string
}

interface StoreContextValue {
  cameras: CameraInfo[]
  filteredCameras: CameraInfo[]
  footfall: FootfallStats | null
  filteredFootfall: FootfallStats | null
  stores: StoreOption[]
  selectedStoreId: string
  selectedStoreName: string
  loading: boolean
  refreshData: () => Promise<void>
  setSelectedStoreId: (storeId: string) => void
  getCameraById: (cameraId: string) => CameraInfo | undefined
}

const StoreContext = createContext<StoreContextValue | null>(null)

export function StoreProvider({ children }: { children: ReactNode }) {
  const [cameras, setCameras] = useState<CameraInfo[]>([])
  const [footfall, setFootfall] = useState<FootfallStats | null>(null)
  const [stores, setStores] = useState<StoreOption[]>([])
  const [selectedStoreId, setSelectedStoreId] = useState('')
  const [selectedStoreName, setSelectedStoreName] = useState('Store')
  const [loading, setLoading] = useState(true)
  const [defaultStoreId, setDefaultStoreId] = useState('default-store')

  const refreshData = async () => {
    setLoading(true)

    try {
      const [cameraRes, configRes] = await Promise.all([
        fetch('/api/v1/cameras'),
        fetch('/api/v1/config'),
      ])

      const cameraData = (await cameraRes.json()) as CameraInfo[]
      const configData = (await configRes.json()) as ConfigResponse

      const configStoreId = configData.store?.store_id || 'default-store'
      const configStoreName = configData.store?.name || configStoreId
      setDefaultStoreId(configStoreId)

      const normalizedCameras = cameraData

      const nextStores = Array.from(
        new Map(
          normalizedCameras.map((camera) => [
            camera.store_id,
            {
              id: camera.store_id,
              name: camera.store_name,
            },
          ])
        ).values()
      )

      if (nextStores.length === 0) {
        nextStores.push({ id: configStoreId, name: configStoreName })
      }

      const activeStoreId =
        selectedStoreId && nextStores.some((store) => store.id === selectedStoreId)
          ? selectedStoreId
          : nextStores[0].id

      const footfallRes = await fetch(
        `/api/v1/footfall/current?store_id=${encodeURIComponent(activeStoreId)}`
      )
      const footfallData = (await footfallRes.json()) as FootfallStats

      setCameras(normalizedCameras)
      setFootfall({
        ...footfallData,
        store_id: footfallData.store_id || activeStoreId,
      })
      setStores(nextStores)

      setSelectedStoreId((currentStoreId) => {
        const nextStoreId =
          currentStoreId && nextStores.some((store) => store.id === currentStoreId)
            ? currentStoreId
            : nextStores[0].id

        const activeStore = nextStores.find((store) => store.id === nextStoreId)
        setSelectedStoreName(activeStore?.name || configStoreName)
        return nextStoreId
      })
    } catch (error) {
      console.error('Failed to load store dashboard data:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refreshData()
  }, [selectedStoreId])

  useEffect(() => {
    const activeStore = stores.find((store) => store.id === selectedStoreId)
    if (activeStore) {
      setSelectedStoreName(activeStore.name)
    }
  }, [selectedStoreId, stores])

  const filteredCameras = cameras.filter(
    (camera) => (camera.store_id || defaultStoreId) === selectedStoreId
  )

  const filteredFootfall =
    footfall && (footfall.store_id || defaultStoreId) === selectedStoreId
      ? footfall
      : stores.length <= 1
      ? footfall
      : null

  const getCameraById = (cameraId: string) =>
    cameras.find((camera) => camera.id === cameraId)

  return (
    <StoreContext.Provider
      value={{
        cameras,
        filteredCameras,
        footfall,
        filteredFootfall,
        stores,
        selectedStoreId,
        selectedStoreName,
        loading,
        refreshData,
        setSelectedStoreId,
        getCameraById,
      }}
    >
      {children}
    </StoreContext.Provider>
  )
}

export function useStoreContext() {
  const context = useContext(StoreContext)
  if (!context) {
    throw new Error('useStoreContext must be used within a StoreProvider')
  }
  return context
}