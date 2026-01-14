export default function Ground() {
  return (
    <>
      {/* Ground plane for shadows */}
      <mesh
        rotation={[-Math.PI / 2, 0, 0]}
        position={[0, 0, 0]}
        receiveShadow
      >
        <planeGeometry args={[100, 100]} />
        <shadowMaterial opacity={0.2} />
      </mesh>
    </>
  )
}
