import { useMemo, useState } from 'react'
import CalibrationWorkbench from './components/CalibrationWorkbench'
import LiveCameraBlueprintGrid from './components/LiveCameraBlueprintGrid'
import StoreOverview, { type StoreMetrics } from './components/StoreOverview'
import StoreSelector from './components/StoreSelector'
import { type StoreAlert } from './components/StoreAlerts'
import { useStoreContext } from './store-context'
import './index.css'

function App() {
  const {
    filteredCameras,
    filteredFootfall,
    stores,
    selectedStoreId,
    selectedStoreName,
    loading,
    refreshData,
    setSelectedStoreId,
  } = useStoreContext()
  const [workspaceMode, setWorkspaceMode] = useState<'stage1' | 'stage2'>('stage1')

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

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <header className="border-b border-gray-800 px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h1 className="text-xl font-bold tracking-tight">
              RetailVision <span className="text-blue-400 text-sm font-normal ml-2">Admin</span>
            </h1>
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
        ) : filteredCameras.length === 0 ? (
          <div className="text-center text-gray-500 mt-20">
            <p className="text-lg">No cameras configured for {selectedStoreName}.</p>
            <p className="text-sm mt-2">
              Add cameras in <code className="text-blue-400">config/default_config.yaml</code> and restart the backend.
            </p>
          </div>
        ) : (
          <div className="space-y-6">
            <StoreOverview
              storeName={selectedStoreName}
              metrics={dashboardMetrics}
              alerts={storeAlerts}
              hasScopedFootfall={filteredFootfall !== null}
            />
            <section className="rounded border border-gray-800 bg-gray-900 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-gray-100">Spatial Workflow</h2>
                  <p className="mt-1 text-xs text-gray-500">
                    Stage 1 builds the shared blueprint. Stage 2 calibrates each camera against that blueprint.
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => setWorkspaceMode('stage1')}
                    className={`rounded px-4 py-2 text-sm font-medium transition-colors ${
                      workspaceMode === 'stage1'
                        ? 'bg-blue-600 text-white'
                        : 'border border-gray-700 bg-gray-800 text-gray-100 hover:bg-gray-700'
                    }`}
                  >
                    Stage 1 Store Map
                  </button>
                  <button
                    onClick={() => setWorkspaceMode('stage2')}
                    className={`rounded px-4 py-2 text-sm font-medium transition-colors ${
                      workspaceMode === 'stage2'
                        ? 'bg-teal-700 text-white'
                        : 'border border-gray-700 bg-gray-800 text-gray-100 hover:bg-gray-700'
                    }`}
                  >
                    Stage 2 Calibration
                  </button>
                </div>
              </div>
            </section>

            {workspaceMode === 'stage1' ? (
              <LiveCameraBlueprintGrid
                cameras={filteredCameras}
                storeId={selectedStoreId}
                storeName={selectedStoreName}
                onSaved={refreshData}
              />
            ) : (
              <CalibrationWorkbench
                cameras={filteredCameras}
                storeId={selectedStoreId}
                storeName={selectedStoreName}
              />
            )}
          </div>
        )}
      </main>
    </div>
  )
}

export default App
