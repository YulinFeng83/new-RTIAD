import { useEffect, useMemo, useState } from 'react'
import CameraSetup from './pages/CameraSetup'
import LiveFeed from './components/LiveFeed'
import StoreOverview, { type StoreMetrics } from './components/StoreOverview'
import StoreSelector from './components/StoreSelector'
import { type StoreAlert } from './components/StoreAlerts'
import { useStoreContext, type CameraInfo } from './store-context'
import './index.css'

type View = 'grid' | 'setup'

function App() {
  const [view, setView] = useState<View>('grid')
  const [setupCameraId, setSetupCameraId] = useState<string>('')
  const {
    filteredCameras,
    filteredFootfall,
    stores,
    selectedStoreId,
    selectedStoreName,
    loading,
    refreshData,
    setSelectedStoreId,
    getCameraById,
  } = useStoreContext()

  const storeAlerts = useMemo<StoreAlert[]>(() => {
    const alerts: StoreAlert[] = []

    if (filteredCameras.length === 0) {
      alerts.push({
        id: 'no-cameras',
        title: 'No cameras in this store',
        detail: 'This store currently has no camera configuration loaded into the dashboard.',
      })
    }

    const camerasWithoutZones = filteredCameras.filter((camera) => camera.zones.length === 0)
    if (camerasWithoutZones.length > 0) {
      alerts.push({
        id: 'missing-zones',
        title: 'Cameras need zone setup',
        detail: `${camerasWithoutZones.length} camera${camerasWithoutZones.length !== 1 ? 's' : ''} in this store still have no configured zones.`,
      })
    }

    return alerts
  }, [filteredCameras])

  const dashboardMetrics = useMemo<StoreMetrics>(() => {
    const zoneCount = filteredCameras.reduce((total, camera) => total + camera.zones.length, 0)
    const indoorCount = filteredCameras.filter((camera) => camera.scene_type === 'indoor').length
    const outdoorCount = filteredCameras.length - indoorCount

    return {
      cameras: filteredCameras.length,
      zones: zoneCount,
      occupancy: filteredFootfall?.current_in_store ?? null,
      entries: filteredFootfall?.total_entries ?? null,
      exits: filteredFootfall?.total_exits ?? null,
      indoorCount,
      outdoorCount,
    }
  }, [filteredCameras, filteredFootfall])

  useEffect(() => {
    if (!setupCameraId) {
      return
    }

    const setupCamera = getCameraById(setupCameraId)
    if (!setupCamera || setupCamera.store_id !== selectedStoreId) {
      setSetupCameraId('')
      setView('grid')
    }
  }, [getCameraById, selectedStoreId, setupCameraId])

  const openSetup = (camId: string) => {
    setSetupCameraId(camId)
    setView('setup')
  }

  const backToGrid = () => {
    setView('grid')
    setSetupCameraId('')
    void refreshData()
  }

  const selectedCamera = setupCameraId ? getCameraById(setupCameraId) : undefined

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <header className="border-b border-gray-800 px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h1 className="text-xl font-bold tracking-tight">
              RetailVision <span className="text-blue-400 text-sm font-normal ml-2">Admin</span>
            </h1>
            {view === 'setup' && (
              <button
                onClick={backToGrid}
                className="text-sm bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded px-3 py-1.5 transition-colors"
              >
                &larr; Store Dashboard
              </button>
            )}
          </div>
          <StoreSelector
            stores={stores}
            selectedStoreId={selectedStoreId}
            cameraCount={filteredCameras.length}
            onChange={setSelectedStoreId}
            onRefresh={() => void refreshData()}
          />
        </div>
      </header>

      <main className="p-6">
        {loading ? (
          <div className="text-center text-gray-500 mt-20">
            <p className="text-lg">Loading store dashboard...</p>
          </div>
        ) : filteredCameras.length === 0 && view === 'grid' ? (
          <div className="text-center text-gray-500 mt-20">
            <p className="text-lg">No cameras configured for {selectedStoreName}.</p>
            <p className="text-sm mt-2">
              Add cameras in <code className="text-blue-400">config/default_config.yaml</code> and restart the backend.
            </p>
          </div>
        ) : view === 'grid' ? (
          <div className="space-y-6">
            <StoreOverview
              storeName={selectedStoreName}
              metrics={dashboardMetrics}
              alerts={storeAlerts}
              hasScopedFootfall={filteredFootfall !== null}
            />
            <MultiCameraGrid cameras={filteredCameras} onSelectCamera={openSetup} />
          </div>
        ) : (
          <CameraSetup
            camera={selectedCamera}
            storeName={selectedStoreName}
            onZoneChange={refreshData}
          />
        )}
      </main>
    </div>
  )
}

function MultiCameraGrid({
  cameras,
  onSelectCamera,
}: {
  cameras: CameraInfo[]
  onSelectCamera: (id: string) => void
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
        <div key={cam.id} className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
          <div className="flex items-center justify-between px-4 py-2 border-b border-gray-800">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold">{cam.id}</span>
              <span
                className={`text-xs px-2 py-0.5 rounded-full ${
                  cam.scene_type === 'indoor'
                    ? 'bg-blue-900 text-blue-300'
                    : 'bg-green-900 text-green-300'
                }`}
              >
                {cam.scene_type}
              </span>
              {cam.zones.length > 0 && (
                <span className="text-xs text-gray-500">
                  {cam.zones.length} zone{cam.zones.length !== 1 ? 's' : ''}
                </span>
              )}
            </div>
            <button
              onClick={() => onSelectCamera(cam.id)}
              className="text-xs bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded px-2.5 py-1 transition-colors"
            >
              Setup Zones
            </button>
          </div>
          <LiveFeed
            cameraId={cam.id}
            className="w-full object-contain"
          />
        </div>
      ))}
    </div>
  )
}

export default App
