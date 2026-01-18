import { useCanvasStore } from '../../store/canvasStore'
import MapContainer from './MapContainer'
import MapCollapsedIcon from './MapCollapsedIcon'
import ConnectionPreview from './ConnectionPreview'

export default function MapLayer() {
  const { maps, mapSelection } = useCanvasStore()

  // Check if we're in connection mode
  const isConnectionMode = mapSelection?.connectionSource !== undefined

  return (
    <div className="absolute inset-0 pointer-events-none">
      {maps.map((map) =>
        map.collapsed ? (
          <MapCollapsedIcon key={map.id} map={map} />
        ) : (
          <MapContainer key={map.id} map={map} />
        )
      )}

      {/* Connection preview line when creating new connection */}
      {isConnectionMode && mapSelection && (
        <ConnectionPreview
          mapId={mapSelection.mapId}
          sourceNodeId={mapSelection.connectionSource!}
        />
      )}
    </div>
  )
}
