import React, { useState } from 'react'

interface Citation {
  id: number
  filename: string
  type: string
}

interface CitationRendererProps {
  content: string
  citations?: Citation[]
}

const CitationRenderer: React.FC<CitationRendererProps> = ({ content, citations = [] }) => {
  const [showCitationModal, setShowCitationModal] = useState(false)
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null)

  // Parse citations from the content
  const parseCitations = (text: string) => {
    const citationRegex = /\[\^(\d+)\]/g
    const matches = [...text.matchAll(citationRegex)]
    const foundCitations: Citation[] = []
    
    matches.forEach(match => {
      const id = parseInt(match[1])
      // Look for citation definition
      const defRegex = new RegExp(`\\[\\^${id}\\]:\\s*(.+)`, 'gm')
      const defMatch = defRegex.exec(text)
      if (defMatch) {
        foundCitations.push({
          id,
          filename: defMatch[1].trim(),
          type: 'document'
        })
      }
    })
    
    return foundCitations
  }

  // Replace citation markers with clickable links
  const renderContentWithCitations = (text: string) => {
    const detectedCitations = parseCitations(text)
    
    // Replace citation markers with clickable spans
    let renderedText = text.replace(/\[\^(\d+)\]/g, (match, id) => {
      const citation = detectedCitations.find(c => c.id === parseInt(id))
      if (citation) {
        return `<span class="citation-link" data-citation-id="${id}" title="Click to view source: ${citation.filename}">[${id}]</span>`
      }
      return match
    })

    // Remove citation definitions from main text (they'll be shown in references)
    renderedText = renderedText.replace(/\n---\n📚 \*\*Sources:\*\*\n[\s\S]*$/, '')
    
    return { text: renderedText, citations: detectedCitations }
  }

  const handleCitationClick = (citationId: number) => {
    const citation = citations.find(c => c.id === citationId)
    if (citation) {
      setSelectedCitation(citation)
      setShowCitationModal(true)
    }
  }

  // Add click handlers after render
  React.useEffect(() => {
    const citationLinks = document.querySelectorAll('.citation-link')
    citationLinks.forEach(link => {
      link.addEventListener('click', (e) => {
        const citationId = parseInt((e.target as HTMLElement).getAttribute('data-citation-id') || '0')
        handleCitationClick(citationId)
      })
    })

    return () => {
      citationLinks.forEach(link => {
        link.removeEventListener('click', handleCitationClick as any)
      })
    }
  }, [content])

  const { text: processedText, citations: detectedCitations } = renderContentWithCitations(content)

  return (
    <>
      {/* Main content with processed citations */}
      <div 
        dangerouslySetInnerHTML={{ __html: processedText }}
        className="citation-content"
      />
      
      {/* Citation Modal */}
      {showCitationModal && selectedCitation && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 rounded-lg max-w-2xl w-full max-h-[80vh] overflow-y-auto">
            <div className="p-6">
              <div className="flex justify-between items-start mb-4">
                <h3 className="text-lg font-semibold text-white">Citation Details</h3>
                <button
                  onClick={() => setShowCitationModal(false)}
                  className="text-gray-400 hover:text-white"
                >
                  <span className="material-icons">close</span>
                </button>
              </div>
              
              <div className="space-y-4">
                <div>
                  <h4 className="font-medium text-teal-400 mb-2">Source Document</h4>
                  <p className="text-gray-300">{selectedCitation.filename}</p>
                </div>
                
                <div>
                  <h4 className="font-medium text-teal-400 mb-2">Citation ID</h4>
                  <p className="text-gray-300">[{selectedCitation.id}]</p>
                </div>
                
                <div>
                  <h4 className="font-medium text-teal-400 mb-2">Type</h4>
                  <p className="text-gray-300 capitalize">{selectedCitation.type}</p>
                </div>
              </div>
              
              <div className="flex justify-end mt-6 space-x-3">
                <button
                  onClick={() => setShowCitationModal(false)}
                  className="px-4 py-2 bg-gray-600 text-white rounded hover:bg-gray-700"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
      
      {/* CSS for citation styling */}
      <style jsx>{`
        .citation-content :global(.citation-link) {
          color: #14b8a6;
          cursor: pointer;
          font-weight: 500;
          text-decoration: none;
          padding: 1px 3px;
          border-radius: 3px;
          background-color: rgba(20, 184, 166, 0.1);
          border: 1px solid rgba(20, 184, 166, 0.3);
          font-size: 0.85em;
          vertical-align: super;
          line-height: 1;
        }
        
        .citation-content :global(.citation-link:hover) {
          background-color: rgba(20, 184, 166, 0.2);
          border-color: rgba(20, 184, 166, 0.5);
        }
      `}</style>
    </>
  )
}

export default CitationRenderer