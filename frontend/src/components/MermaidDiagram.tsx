import React, { useEffect, useRef, useState, memo, useMemo } from 'react'
import mermaid from 'mermaid'

interface MermaidDiagramProps {
  chart: string
  id: string
}

const MermaidDiagram: React.FC<MermaidDiagramProps> = memo(({ chart, id }) => {
  const ref = useRef<HTMLDivElement>(null)
  const [hasError, setHasError] = useState(false)
  const renderedChartRef = useRef<string>('')
  const isRenderingRef = useRef(false)
  
  // Memoize the chart content to prevent unnecessary re-renders
  const chartContent = useMemo(() => chart.trim(), [chart])

  useEffect(() => {
    let mounted = true
    
    const renderDiagram = async () => {
      if (!ref.current || !chartContent || !mounted) return
      
      // Prevent re-rendering the same content
      const currentContent = chartContent + id
      if (renderedChartRef.current === currentContent || isRenderingRef.current) {
        console.log('🔄 Skipping Mermaid re-render - content unchanged')
        return
      }
      
      isRenderingRef.current = true
      console.log('🎨 Rendering new Mermaid content:', chartContent.substring(0, 50) + '...')
      
      try {
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
        if (!chartContent) {
          throw new Error('Empty chart content')
        }
        
        // Render the mermaid diagram
        if (ref.current && mounted) {
          const { svg } = await mermaid.render(uniqueId, chartContent)
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
            
            // Mark as successfully rendered and store content
            renderedChartRef.current = currentContent
            isRenderingRef.current = false
            
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
        console.error('Chart content:', chartContent)
        console.error('Chart length:', chartContent.length)
        console.error('Chart first 200 chars:', chartContent.substring(0, 200))
        isRenderingRef.current = false
        if (mounted && ref.current) {
          // Show error inline instead of crashing
          const errorMessage = typeof error === 'object' && error ? (error as any).message || String(error) : String(error)
          ref.current.innerHTML = `
            <div style="padding: 16px; background: #fee; border: 1px solid #fcc; border-radius: 8px; color: #c00;">
              <strong>Mermaid Rendering Error</strong><br/>
              <details style="margin-top: 8px;">
                <summary style="cursor: pointer;">Show error details</summary>
                <pre style="margin-top: 8px; font-size: 12px; overflow-x: auto;">${errorMessage}</pre>
              </details>
            </div>
          `
          setHasError(true)
        }
      }
    }

    // Add a small delay to prevent rapid re-renders
    const timeoutId = setTimeout(renderDiagram, 100)
    
    return () => {
      mounted = false
      clearTimeout(timeoutId)
      isRenderingRef.current = false
    }
  }, [chartContent, id])

  if (hasError) {
    return (
      <div className="my-4 p-4 bg-red-900/20 border border-red-500 rounded-lg text-red-300">
        <p className="font-semibold">Diagram Error</p>
        <p className="text-sm">Failed to render Mermaid diagram. Please check the syntax.</p>
        <details className="mt-2">
          <summary className="cursor-pointer text-sm">Show diagram code</summary>
          <pre className="mt-2 text-xs bg-gray-800 p-2 rounded overflow-x-auto">{chartContent}</pre>
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
})

export default MermaidDiagram