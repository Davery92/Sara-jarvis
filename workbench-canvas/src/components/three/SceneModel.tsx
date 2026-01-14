import { useState, useEffect, useRef, useCallback } from 'react'
import { useThree, ThreeEvent } from '@react-three/fiber'
import { Outlines } from '@react-three/drei'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import * as THREE from 'three'
import type { SceneObject } from '../../types'
import { APP_CONFIG } from '../../config'
import { getToken } from '../../services/api'

interface SceneModelProps {
  sceneObject: SceneObject
  isSelected: boolean
  onSelect: () => void
  onUpdate: (updates: Partial<SceneObject>) => void
}

export default function SceneModel({ sceneObject, isSelected, onSelect, onUpdate }: SceneModelProps) {
  const [geometry, setGeometry] = useState<THREE.BufferGeometry | null>(null)
  const [object3D, setObject3D] = useState<THREE.Object3D | null>(null)
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [baseScale, setBaseScale] = useState(1)

  const groupRef = useRef<THREE.Group>(null)
  const { gl, camera } = useThree()

  // Drag state
  const isDragging = useRef(false)
  const dragStart = useRef<{ x: number; y: number; shiftKey: boolean } | null>(null)
  const initialRotation = useRef<{ x: number; y: number; z: number }>({ x: 0, y: 0, z: 0 })
  const initialPosition = useRef<{ x: number; y: number; z: number }>({ x: 0, y: 0, z: 0 })

  // Build full URL for the model
  const modelUrl = sceneObject.modelUrl.startsWith('http')
    ? sceneObject.modelUrl
    : `${APP_CONFIG.apiUrl}${sceneObject.modelUrl}`

  // Fetch model with auth and create blob URL
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
          throw new Error(`Failed to load model: ${response.status}`)
        }

        const blob = await response.blob()
        if (!cancelled) {
          const url = URL.createObjectURL(blob)
          setBlobUrl(url)
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
      if (blobUrl) {
        URL.revokeObjectURL(blobUrl)
      }
    }
  }, [modelUrl])

  // Load geometry from blob URL
  useEffect(() => {
    if (!blobUrl) return

    const format = sceneObject.format.toLowerCase()

    const loadModel = () => {
      switch (format) {
        case 'stl': {
          const loader = new STLLoader()
          loader.load(
            blobUrl,
            (geo) => {
              geo.center()
              geo.computeBoundingBox()

              // Calculate scale to normalize size
              const box = geo.boundingBox
              if (box) {
                const size = box.getSize(new THREE.Vector3())
                const maxDim = Math.max(size.x, size.y, size.z)
                setBaseScale(2 / maxDim)
              }

              setGeometry(geo)
              setLoading(false)
            },
            undefined,
            (err) => {
              console.error('STL load error:', err)
              setError('Failed to load STL')
              setLoading(false)
            }
          )
          break
        }
        case 'obj': {
          const loader = new OBJLoader()
          loader.load(
            blobUrl,
            (obj) => {
              // Center the object
              const box = new THREE.Box3().setFromObject(obj)
              const center = box.getCenter(new THREE.Vector3())
              obj.position.sub(center)

              // Calculate scale
              const size = box.getSize(new THREE.Vector3())
              const maxDim = Math.max(size.x, size.y, size.z)
              setBaseScale(2 / maxDim)

              // Apply material
              obj.traverse((child) => {
                if (child instanceof THREE.Mesh) {
                  child.material = new THREE.MeshStandardMaterial({
                    color: '#6b7280',
                    metalness: 0.3,
                    roughness: 0.6,
                  })
                  child.castShadow = true
                  child.receiveShadow = true
                }
              })

              setObject3D(obj)
              setLoading(false)
            },
            undefined,
            (err) => {
              console.error('OBJ load error:', err)
              setError('Failed to load OBJ')
              setLoading(false)
            }
          )
          break
        }
        case 'gltf':
        case 'glb': {
          const loader = new GLTFLoader()
          loader.load(
            blobUrl,
            (gltf) => {
              // Center the scene
              const box = new THREE.Box3().setFromObject(gltf.scene)
              const center = box.getCenter(new THREE.Vector3())
              gltf.scene.position.sub(center)

              // Calculate scale
              const size = box.getSize(new THREE.Vector3())
              const maxDim = Math.max(size.x, size.y, size.z)
              setBaseScale(2 / maxDim)

              gltf.scene.traverse((child) => {
                if (child instanceof THREE.Mesh) {
                  child.castShadow = true
                  child.receiveShadow = true
                }
              })

              setObject3D(gltf.scene)
              setLoading(false)
            },
            undefined,
            (err) => {
              console.error('GLTF load error:', err)
              setError('Failed to load GLTF')
              setLoading(false)
            }
          )
          break
        }
      }
    }

    loadModel()
  }, [blobUrl, sceneObject.format])

  // Handle pointer down
  const handlePointerDown = useCallback((e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation()
    onSelect()

    isDragging.current = true
    dragStart.current = { x: e.clientX, y: e.clientY, shiftKey: e.shiftKey }
    initialRotation.current = { ...sceneObject.rotation }
    initialPosition.current = { ...sceneObject.position }

    // Capture pointer for drag
    ;(e.target as HTMLElement)?.setPointerCapture?.(e.pointerId)
  }, [onSelect, sceneObject.rotation, sceneObject.position])

  // Handle pointer move
  const handlePointerMove = useCallback((e: ThreeEvent<PointerEvent>) => {
    if (!isDragging.current || !dragStart.current) return

    const dx = e.clientX - dragStart.current.x
    const dy = e.clientY - dragStart.current.y

    if (dragStart.current.shiftKey || e.shiftKey) {
      // Move mode - shift+drag moves on ground plane
      const moveSensitivity = 0.02
      onUpdate({
        position: {
          x: initialPosition.current.x + dx * moveSensitivity,
          y: sceneObject.position.y, // Keep Y the same
          z: initialPosition.current.z + dy * moveSensitivity,
        },
      })
    } else {
      // Rotate mode - drag rotates
      const rotateSensitivity = 0.01
      onUpdate({
        rotation: {
          x: initialRotation.current.x - dy * rotateSensitivity,
          y: initialRotation.current.y + dx * rotateSensitivity,
          z: sceneObject.rotation.z,
        },
      })
    }
  }, [onUpdate, sceneObject.position.y, sceneObject.rotation.z])

  // Handle pointer up
  const handlePointerUp = useCallback((e: ThreeEvent<PointerEvent>) => {
    isDragging.current = false
    dragStart.current = null
    ;(e.target as HTMLElement)?.releasePointerCapture?.(e.pointerId)
  }, [])

  // Handle scroll for scaling
  const handleWheel = useCallback((e: ThreeEvent<WheelEvent>) => {
    e.stopPropagation()
    const delta = -e.deltaY * 0.001
    const newScale = Math.max(0.1, Math.min(10, sceneObject.scale * (1 + delta)))
    onUpdate({ scale: newScale })
  }, [sceneObject.scale, onUpdate])

  if (loading) {
    return (
      <group position={[sceneObject.position.x, sceneObject.position.y, sceneObject.position.z]}>
        <mesh>
          <boxGeometry args={[0.5, 0.5, 0.5]} />
          <meshStandardMaterial color="#4a5568" wireframe />
        </mesh>
      </group>
    )
  }

  if (error) {
    return (
      <group position={[sceneObject.position.x, sceneObject.position.y, sceneObject.position.z]}>
        <mesh>
          <boxGeometry args={[0.5, 0.5, 0.5]} />
          <meshStandardMaterial color="#ef4444" />
        </mesh>
      </group>
    )
  }

  const totalScale = baseScale * sceneObject.scale

  // Render STL (geometry-based)
  if (geometry) {
    return (
      <group
        ref={groupRef}
        position={[sceneObject.position.x, sceneObject.position.y + 1, sceneObject.position.z]}
        rotation={[sceneObject.rotation.x, sceneObject.rotation.y, sceneObject.rotation.z]}
        scale={[totalScale, totalScale, totalScale]}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onWheel={handleWheel}
      >
        <mesh geometry={geometry} castShadow receiveShadow>
          <meshStandardMaterial
            color={isSelected ? '#14b8a6' : '#6b7280'}
            metalness={0.3}
            roughness={0.6}
          />
          {isSelected && (
            <Outlines thickness={0.05} color="#14b8a6" />
          )}
        </mesh>
      </group>
    )
  }

  // Render OBJ/GLTF (object-based)
  if (object3D) {
    // Clone the object to avoid issues with primitive re-use
    const clonedObject = object3D.clone()

    // Update material colors for selection
    clonedObject.traverse((child) => {
      if (child instanceof THREE.Mesh && child.material) {
        const mat = child.material as THREE.MeshStandardMaterial
        if (isSelected && mat.color) {
          mat.color.setHex(0x14b8a6)
        }
      }
    })

    return (
      <group
        ref={groupRef}
        position={[sceneObject.position.x, sceneObject.position.y + 1, sceneObject.position.z]}
        rotation={[sceneObject.rotation.x, sceneObject.rotation.y, sceneObject.rotation.z]}
        scale={[totalScale, totalScale, totalScale]}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onWheel={handleWheel}
      >
        <primitive object={clonedObject} />
      </group>
    )
  }

  return null
}
