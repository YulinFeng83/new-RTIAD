/**
 * LiveFeed — displays the annotated MJPEG stream from the backend.
 *
 * Uses a simple <img> tag with the MJPEG URL. All visual overlays
 * (bboxes, labels, zones, stats HUD) are already rendered on the
 * frames by the Python backend's overlay renderer.
 */

import { useRef, useEffect, useState } from 'react'

interface LiveFeedProps {
  cameraId: string
  className?: string
  onLoad?: (width: number, height: number) => void
}

export default function LiveFeed({ cameraId, className = '', onLoad }: LiveFeedProps) {
  const imgRef = useRef<HTMLImageElement>(null)
  const [error, setError] = useState(false)

  const feedUrl = `/api/v1/cameras/${cameraId}/feed`

  useEffect(() => {
    setError(false)
  }, [cameraId])

  const handleLoad = () => {
    if (imgRef.current && onLoad) {
      onLoad(imgRef.current.naturalWidth, imgRef.current.naturalHeight)
    }
  }

  if (error) {
    return (
      <div className={`flex items-center justify-center bg-gray-900 rounded-lg min-h-[300px] ${className}`}>
        <div className="text-center text-gray-500">
          <p className="text-lg">No feed available</p>
          <p className="text-sm mt-1">Camera: {cameraId}</p>
          <button
            onClick={() => setError(false)}
            className="mt-3 text-sm text-blue-400 hover:text-blue-300"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  return (
    <img
      ref={imgRef}
      src={feedUrl}
      alt={`Live feed: ${cameraId}`}
      className={`rounded-lg ${className}`}
      onLoad={handleLoad}
      onError={() => setError(true)}
    />
  )
}
