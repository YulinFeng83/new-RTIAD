import { useState, useEffect } from 'react'
import CameraSetup from './pages/CameraSetup'
import LiveFeed from './components/LiveFeed'
import './index.css'

interface CameraInfo {
  id: string
  url: string
  scene_type: string
  zones: any[]
}

type View = 'grid' | 'setup'

function App() {
  const [cameras, setCameras] = useState<CameraInfo[]>([])
  const [view, setView] = useState<View>('grid')
  const [setupCameraId, setSetupCameraId] = useState<string>('')

  useEffect(() => {
    fetchCameras()
  }, [])

  const fetchCameras = async () => {
    try {
      const res = await fetch('/api/v1/cameras')
      const data = await res.json()
      setCameras(data)
    } catch (err) {
      console.error('Failed to fetch cameras:', err)
    }
  }

  const openSetup = (camId: string) => {
    setSetupCameraId(camId)
    setView('setup')
  }

  const backToGrid = () => {
    setView('grid')
    setSetupCameraId('')
    fetchCameras()
  }

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
                &larr; All Cameras
              </button>
            )}
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-500">
              {cameras.length} camera{cameras.length !== 1 ? 's' : ''}
            </span>
            <button
              onClick={fetchCameras}
              className="text-sm bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded px-3 py-1.5 transition-colors"
            >
              Refresh
            </button>
          </div>
        </div>
      </header>

      <main className="p-6">
        {cameras.length === 0 ? (
          <div className="text-center text-gray-500 mt-20">
            <p className="text-lg">No cameras configured.</p>
            <p className="text-sm mt-2">
              Add cameras in <code className="text-blue-400">config/default_config.yaml</code> and restart the backend.
            </p>
          </div>
        ) : view === 'grid' ? (
          <MultiCameraGrid cameras={cameras} onSelectCamera={openSetup} />
        ) : (
          <CameraSetup
            cameraId={setupCameraId}
            onZoneChange={fetchCameras}
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
