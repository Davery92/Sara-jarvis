import React, { useEffect, useRef, useState } from 'react'
import mermaid from 'mermaid'

interface MermaidDiagramProps {
  chart: string
  id: string
}

const MermaidDiagram: React.FC<MermaidDiagramProps> = ({ chart, id }) => {
  const ref = useRef<HTMLDivElement>(null)
  const [hasError, setHasError] = useState(false)
  
  // console.log('🚀 MermaidDiagram component mounted with props:', { id, chartLength: chart.length, chartPreview: chart.substring(0, 100) + '...' })

  useEffect(() => {
    if (hasError) return
    
    let mounted = true
    
    const renderDiagram = async () => {
      if (!ref.current || !chart || !mounted) return
      
      try {
        // console.log('🔧 Initializing Mermaid...')
        // Initialize mermaid with minimal working config
        mermaid.initialize({
          startOnLoad: false,
          theme: 'default',
          securityLevel: 'loose'
        })
        
        // Clear any previous content
        ref.current.innerHTML = ''
        
        // Generate unique ID for this diagram (must start with letter for valid CSS selector)
        const uniqueId = `mermaid-${id.replace(/[^a-zA-Z0-9]/g, '')}-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
        
        // Validate chart syntax before rendering
        if (!chart.trim()) {
          throw new Error('Empty chart content')
        }
        
        console.log('🎨 Rendering Mermaid chart:', chart.substring(0, 100) + '...')
        console.log('🆔 Using unique ID:', uniqueId)
        
        // Render the mermaid diagram
        if (ref.current && mounted) {
          const { svg } = await mermaid.render(uniqueId, chart)
          console.log('✅ Mermaid SVG generated (length:', svg.length, '):', svg.substring(0, 300) + '...')
          
          // Check if SVG contains actual content by looking for common mermaid elements
          const hasNodes = svg.includes('<g class="nodes"') || svg.includes('class="node"')
          const hasEdges = svg.includes('<g class="edgePaths"') || svg.includes('class="edge"')
          const hasText = svg.includes('<text') || svg.includes('tspan')
          console.log('🔍 SVG content analysis:', { hasNodes, hasEdges, hasText })
          
          if (!hasNodes && !hasEdges) {
            console.warn('⚠️ SVG appears to be empty - no nodes or edges found!')
          }
          
          if (mounted && ref.current) {
            // Insert SVG directly into the container
            ref.current.innerHTML = svg
            console.log('🎯 SVG inserted into container, content length:', ref.current.innerHTML.length)
            
            // Check SVG dimensions and fix height issue
            const svgElement = ref.current.querySelector('svg')
            if (svgElement) {
              console.log('📐 SVG dimensions:', {
                width: svgElement.getAttribute('width'),
                height: svgElement.getAttribute('height'),
                viewBox: svgElement.getAttribute('viewBox'),
                style: svgElement.getAttribute('style')
              })
              
              // Fix missing height by extracting from viewBox
              if (!svgElement.getAttribute('height') && svgElement.getAttribute('viewBox')) {
                const viewBox = svgElement.getAttribute('viewBox')
                const parts = viewBox.split(' ')
                if (parts.length === 4) {
                  const height = parts[3]
                  svgElement.setAttribute('height', height)
                  console.log('🔧 Fixed SVG height to:', height)
                }
              }
              
              // Just ensure SVG is visible
              svgElement.style.display = 'block'
              console.log('🎨 SVG element count check:', {
                texts: svgElement.querySelectorAll('text').length,
                tspans: svgElement.querySelectorAll('tspan').length,
                paths: svgElement.querySelectorAll('path').length,
                rects: svgElement.querySelectorAll('rect').length,
                circles: svgElement.querySelectorAll('circle').length,
                polygons: svgElement.querySelectorAll('polygon').length
              })
            }
          }
        }
        
      } catch (error) {
        console.error('Mermaid rendering error:', error)
        if (mounted) {
          setHasError(true)
        }
      }
    }

    // Add a small delay to prevent rapid re-renders
    const timeoutId = setTimeout(renderDiagram, 100)
    
    return () => {
      mounted = false
      clearTimeout(timeoutId)
    }
  }, [chart, id, hasError])

  if (hasError) {
    return (
      <div className="my-4 p-4 bg-red-900/20 border border-red-500 rounded-lg text-red-300">
        <p className="font-semibold">Diagram Error</p>
        <p className="text-sm">Failed to render Mermaid diagram. Please check the syntax.</p>
        <details className="mt-2">
          <summary className="cursor-pointer text-sm">Show diagram code</summary>
          <pre className="mt-2 text-xs bg-gray-800 p-2 rounded overflow-x-auto">{chart}</pre>
        </details>
      </div>
    )
  }

  return (
    <div 
      ref={ref} 
      className="my-4 p-4 bg-white rounded-lg border border-gray-300 overflow-x-auto"
      style={{ 
        minHeight: '100px'
      }}
    />
  )
}

export default MermaidDiagram