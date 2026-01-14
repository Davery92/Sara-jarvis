import { useState, useEffect, useRef, Suspense } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, Environment, Center, Grid } from '@react-three/drei'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import * as THREE from 'three'
import { Box, Loader2, AlertCircle, RotateCcw, ZoomIn, ZoomOut, Move } from 'lucide-react'
import type { ModelViewerWindowData } from '../../types'
import { APP_CONFIG } from '../../config'
import { getToken } from '../../services/api'

interface ModelViewerContentProps {
  data: ModelViewerWindowData
  windowId: string
}

// STL Model component - loads geometry directly from blob URL
function STLModel({ url }: { url: string }) {
  const [geometry, setGeometry] = useState<THREE.BufferGeometry | null>(null)
  const meshRef = useRef<THREE.Mesh>(null)

  useEffect(() => {
    const loader = new STLLoader()
    loader.load(
      url,
      (geo) => {
        geo.center()
        geo.computeBoundingBox()
        setGeometry(geo)
      },
      undefined,
      (err) => console.error('STL load error:', err)
    )
  }, [url])

  useEffect(() => {
    if (meshRef.current && geometry) {
      const box = geometry.boundingBox
      if (box) {
        const size = box.getSize(new THREE.Vector3())
        const maxDim = Math.max(size.x, size.y, size.z)
        const scale = 2 / maxDim
        meshRef.current.scale.setScalar(scale)
      }
    }
  }, [geometry])

  if (!geometry) return null

  return (
    <mesh ref={meshRef} geometry={geometry} castShadow receiveShadow>
      <meshStandardMaterial color="#6b7280" metalness={0.3} roughness={0.6} />
    </mesh>
  )
}

// OBJ Model component - loads directly from blob URL
function OBJModel({ url }: { url: string }) {
  const [obj, setObj] = useState<THREE.Group | null>(null)
  const groupRef = useRef<THREE.Group>(null)

  useEffect(() => {
    const loader = new OBJLoader()
    loader.load(
      url,
      (loaded) => {
        const box = new THREE.Box3().setFromObject(loaded)
        const center = box.getCenter(new THREE.Vector3())
        loaded.position.sub(center)

        // Apply default material to meshes
        loaded.traverse((child) => {
          if (child instanceof THREE.Mesh) {
            if (!child.material || (child.material as THREE.Material).type === 'MeshBasicMaterial') {
              child.material = new THREE.MeshStandardMaterial({
                color: '#6b7280',
                metalness: 0.3,
                roughness: 0.6,
              })
            }
            child.castShadow = true
            child.receiveShadow = true
          }
        })
        setObj(loaded)
      },
      undefined,
      (err) => console.error('OBJ load error:', err)
    )
  }, [url])

  useEffect(() => {
    if (groupRef.current && obj) {
      const box = new THREE.Box3().setFromObject(obj)
      const size = box.getSize(new THREE.Vector3())
      const maxDim = Math.max(size.x, size.y, size.z)
      const scale = 2 / maxDim
      groupRef.current.scale.setScalar(scale)
    }
  }, [obj])

  if (!obj) return null

  return <primitive ref={groupRef} object={obj} />
}

// GLTF Model component - loads directly from blob URL
function GLTFModel({ url }: { url: string }) {
  const [scene, setScene] = useState<THREE.Group | null>(null)
  const groupRef = useRef<THREE.Group>(null)

  useEffect(() => {
    const loader = new GLTFLoader()
    loader.load(
      url,
      (gltf) => {
        const box = new THREE.Box3().setFromObject(gltf.scene)
        const center = box.getCenter(new THREE.Vector3())
        gltf.scene.position.sub(center)

        gltf.scene.traverse((child) => {
          if (child instanceof THREE.Mesh) {
            child.castShadow = true
            child.receiveShadow = true
          }
        })
        setScene(gltf.scene)
      },
      undefined,
      (err) => console.error('GLTF load error:', err)
    )
  }, [url])

  useEffect(() => {
    if (groupRef.current && scene) {
      const box = new THREE.Box3().setFromObject(scene)
      const size = box.getSize(new THREE.Vector3())
      const maxDim = Math.max(size.x, size.y, size.z)
      const scale = 2 / maxDim
      groupRef.current.scale.setScalar(scale)
    }
  }, [scene])

  if (!scene) return null

  return <primitive ref={groupRef} object={scene} />
}

// Model loader that chooses the right component based on format
function Model({ url, format }: { url: string; format: string }) {
  switch (format.toLowerCase()) {
    case 'stl':
      return <STLModel url={url} />
    case 'obj':
      return <OBJModel url={url} />
    case 'gltf':
    case 'glb':
      return <GLTFModel url={url} />
    default:
      return null
  }
}

// Scene setup component
function Scene({ url, format }: { url: string; format: string }) {
  return (
    <>
      {/* Lighting */}
      <ambientLight intensity={0.5} />
      <directionalLight
        position={[5, 5, 5]}
        intensity={1}
        castShadow
        shadow-mapSize={[1024, 1024]}
      />
      <directionalLight position={[-5, 3, -5]} intensity={0.4} />

      {/* Environment for reflections */}
      <Environment preset="studio" />

      {/* Grid floor */}
      <Grid
        position={[0, -1.5, 0]}
        args={[10, 10]}
        cellSize={0.5}
        cellThickness={0.5}
        cellColor="#4a5568"
        sectionSize={2}
        sectionThickness={1}
        sectionColor="#718096"
        fadeDistance={15}
        fadeStrength={1}
        followCamera={false}
      />

      {/* Model */}
      <Center>
        <Model url={url} format={format} />
      </Center>

      {/* Controls */}
      <OrbitControls
        makeDefault
        enablePan={true}
        enableZoom={true}
        enableRotate={true}
        minDistance={1}
        maxDistance={20}
      />
    </>
  )
}

// Loading fallback
function LoadingFallback() {
  return (
    <mesh>
      <boxGeometry args={[1, 1, 1]} />
      <meshStandardMaterial color="#4a5568" wireframe />
    </mesh>
  )
}

// Error boundary for 3D loading errors
function ErrorFallback({ error, onRetry }: { error: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center h-full bg-canvas-bg text-canvas-text">
      <AlertCircle size={48} className="text-red-500 mb-4" />
      <p className="text-lg font-medium mb-2">Failed to load model</p>
      <p className="text-sm text-canvas-muted mb-4 max-w-xs text-center">{error}</p>
      <button
        onClick={onRetry}
        className="px-4 py-2 bg-teal-500 hover:bg-teal-600 rounded-lg text-white flex items-center gap-2"
      >
        <RotateCcw size={16} />
        Retry
      </button>
    </div>
  )
}

export default function ModelViewerContent({ data, windowId }: ModelViewerContentProps) {
  const [error, setError] = useState<string | null>(null)
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [key, setKey] = useState(0) // For forcing re-render on retry

  // Build full URL for the model
  const modelUrl = data.modelUrl.startsWith('http')
    ? data.modelUrl
    : `${APP_CONFIG.apiUrl}${data.modelUrl}`

  // Fetch the model with auth and create a blob URL
  useEffect(() => {
    let cancelled = false
    const fetchModel = async () => {
      setLoading(true)
      setError(null)

      try {
        const token = getToken()
        const response = await fetch(modelUrl, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          credentials: 'include',
        })

        if (!response.ok) {
          throw new Error(`Failed to load model: ${response.status} ${response.statusText}`)
        }

        const blob = await response.blob()
        if (!cancelled) {
          const url = URL.createObjectURL(blob)
          setBlobUrl(url)
          setLoading(false)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load model')
          setLoading(false)
        }
      }
    }

    fetchModel()

    return () => {
      cancelled = true
      // Clean up blob URL on unmount
      if (blobUrl) {
        URL.revokeObjectURL(blobUrl)
      }
    }
  }, [modelUrl, key])

  const handleRetry = () => {
    setError(null)
    setBlobUrl(null)
    setKey((k) => k + 1)
  }

  if (error) {
    return <ErrorFallback error={error} onRetry={handleRetry} />
  }

  return (
    <div className="flex flex-col h-full bg-gray-900">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-canvas-border bg-canvas-surface">
        <div className="flex items-center gap-2">
          <Box size={18} className="text-teal-500" />
          <span className="text-sm font-medium text-white truncate max-w-[200px]">
            {data.filename}
          </span>
          <span className="text-xs text-canvas-muted uppercase">
            {data.format}
          </span>
        </div>
        <div className="flex items-center gap-1 text-xs text-canvas-muted">
          <Move size={12} />
          <span>Drag to orbit</span>
          <span className="mx-1">|</span>
          <ZoomIn size={12} />
          <span>Scroll to zoom</span>
        </div>
      </div>

      {/* 3D Canvas */}
      <div className="flex-1 relative">
        {loading ? (
          <div className="flex items-center justify-center h-full">
            <Loader2 size={48} className="animate-spin text-teal-500" />
          </div>
        ) : blobUrl ? (
          <Canvas
            key={key}
            shadows
            camera={{ position: [3, 3, 3], fov: 50 }}
            onError={(e) => {
              console.error('Canvas error:', e)
              setError('Failed to initialize 3D renderer')
            }}
          >
            <Suspense fallback={<LoadingFallback />}>
              <Scene url={blobUrl} format={data.format} />
            </Suspense>
          </Canvas>
        ) : null}

        {/* Model info */}
        <div className="absolute bottom-4 left-4 text-xs text-canvas-muted">
          Model ID: {data.modelId.slice(0, 8)}...
        </div>
      </div>
    </div>
  )
}
