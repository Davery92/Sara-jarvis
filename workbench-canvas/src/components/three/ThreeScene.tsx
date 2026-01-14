import { useRef, useEffect, useCallback, useState } from 'react'
import { Canvas, useThree, useFrame } from '@react-three/fiber'
import { Environment } from '@react-three/drei'
import * as THREE from 'three'
import { useCanvasStore } from '../../store/canvasStore'
import SceneModel from './SceneModel'
import Ground from './Ground'

// Camera controller that syncs with 2D canvas transform
function CameraController() {
  const { camera } = useThree()
  const transform = useCanvasStore((state) => state.transform)

  useFrame(() => {
    // Map 2D canvas transform to 3D camera position
    // Scale affects zoom (camera distance), pan affects camera target
    const baseDistance = 10
    const distance = baseDistance / transform.scale

    // Convert 2D pan to 3D camera position offset
    const offsetX = -transform.x / 100 / transform.scale
    const offsetZ = -transform.y / 100 / transform.scale

    // Position camera looking down at an angle
    camera.position.set(offsetX + distance * 0.5, distance * 0.8, offsetZ + distance * 0.5)
    camera.lookAt(offsetX, 0, offsetZ)
  })

  return null
}

// Scene content component
function SceneContent() {
  const sceneObjects = useCanvasStore((state) => state.sceneObjects)
  const selectedObjectId = useCanvasStore((state) => state.selectedObjectId)
  const selectObject = useCanvasStore((state) => state.selectObject)
  const updateSceneObject = useCanvasStore((state) => state.updateSceneObject)

  // State for drag interactions
  const [isDragging, setIsDragging] = useState(false)
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null)
  const [dragMode, setDragMode] = useState<'rotate' | 'move'>('rotate')

  // Handle pointer down on empty space
  const handlePointerMissed = useCallback(() => {
    selectObject(null)
  }, [selectObject])

  return (
    <>
      {/* Lighting */}
      <ambientLight intensity={0.5} />
      <directionalLight
        position={[10, 15, 10]}
        intensity={1}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-far={50}
        shadow-camera-left={-20}
        shadow-camera-right={20}
        shadow-camera-top={20}
        shadow-camera-bottom={-20}
      />
      <directionalLight position={[-10, 8, -10]} intensity={0.3} />

      {/* Environment for reflections */}
      <Environment preset="studio" />

      {/* Ground plane */}
      <Ground />

      {/* Camera controller */}
      <CameraController />

      {/* Render scene objects */}
      {sceneObjects.map((obj) => (
        <SceneModel
          key={obj.id}
          sceneObject={obj}
          isSelected={selectedObjectId === obj.id}
          onSelect={() => selectObject(obj.id)}
          onUpdate={(updates) => updateSceneObject(obj.id, updates)}
        />
      ))}
    </>
  )
}

interface ThreeSceneProps {
  className?: string
}

export default function ThreeScene({ className }: ThreeSceneProps) {
  const selectObject = useCanvasStore((state) => state.selectObject)
  const selectedObjectId = useCanvasStore((state) => state.selectedObjectId)
  const removeSceneObject = useCanvasStore((state) => state.removeSceneObject)

  // Handle keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Delete selected object
      if ((e.key === 'Delete' || e.key === 'Backspace') && selectedObjectId) {
        // Don't delete if user is typing in an input
        if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
          return
        }
        removeSceneObject(selectedObjectId)
      }

      // Escape to deselect
      if (e.key === 'Escape') {
        selectObject(null)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedObjectId, removeSceneObject, selectObject])

  return (
    <div className={className}>
      <Canvas
        shadows
        camera={{ position: [8, 8, 8], fov: 50 }}
        onPointerMissed={() => selectObject(null)}
        gl={{ antialias: true, alpha: true }}
        style={{ background: 'transparent' }}
      >
        <SceneContent />
      </Canvas>
    </div>
  )
}
