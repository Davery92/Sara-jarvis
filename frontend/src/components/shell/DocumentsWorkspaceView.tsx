import React from 'react'

interface DocumentsWorkspaceViewProps {
  selectedFile: File | null
  uploading: boolean
  documents: any[]
  editingDocumentId: string | number | null
  editingDocumentTitle: string
  onSelectFile: (file: File | null) => void
  onUploadDocument: (file: File) => void
  onEditDocumentTitleChange: (value: string) => void
  onStartEditDocumentTitle: (doc: any) => void
  onUpdateDocumentTitle: (docId: string, title: string) => void
  onCancelEditDocumentTitle: () => void
  onDownloadDocument: (docId: string, filename: string) => void
  onDeleteDocument: (docId: string) => void
}

const DocumentsWorkspaceView: React.FC<DocumentsWorkspaceViewProps> = ({
  selectedFile,
  uploading,
  documents,
  editingDocumentId,
  editingDocumentTitle,
  onSelectFile,
  onUploadDocument,
  onEditDocumentTitleChange,
  onStartEditDocumentTitle,
  onUpdateDocumentTitle,
  onCancelEditDocumentTitle,
  onDownloadDocument,
  onDeleteDocument,
}) => {
  return (
    <div className="flex-1 overflow-y-auto min-h-0 space-y-6">
      <div className="bg-card border border-card rounded-md p-6">
        <h2 className="text-lg font-semibold mb-4">UPLOAD DOCUMENT</h2>
        <div className="space-y-4">
          <div className="border-2 border-dashed border-gray-600 rounded-lg p-8 text-center">
            <input
              type="file"
              id="document-upload"
              className="hidden"
              accept=".pdf,.doc,.docx,.txt,.md"
              onChange={(event) => onSelectFile(event.target.files?.[0] ?? null)}
            />
            <label htmlFor="document-upload" className="cursor-pointer">
              <div className="space-y-2">
                <span className="material-icons text-4xl text-gray-400">cloud_upload</span>
                <p className="text-gray-400">Click to select a document or drag and drop</p>
                <p className="text-sm text-gray-500">Supports PDF, DOC, DOCX, TXT, MD files</p>
              </div>
            </label>
          </div>

          {selectedFile && (
            <div className="bg-gray-800 p-4 rounded-lg">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-3">
                  <span className="material-icons text-teal-400">description</span>
                  <div>
                    <p className="text-white font-medium">{selectedFile.name}</p>
                    <p className="text-sm text-gray-400">{(selectedFile.size / 1024 / 1024).toFixed(2)} MB</p>
                  </div>
                </div>
                <div className="space-x-2">
                  <button
                    onClick={() => onUploadDocument(selectedFile)}
                    disabled={uploading}
                    className="bg-teal-600 hover:bg-teal-700 text-white px-4 py-2 rounded-lg disabled:opacity-50"
                  >
                    {uploading ? 'Uploading...' : 'Upload'}
                  </button>
                  <button
                    onClick={() => onSelectFile(null)}
                    className="bg-gray-600 hover:bg-gray-700 text-white px-4 py-2 rounded-lg"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="bg-card border border-card rounded-md p-6">
        <h2 className="text-lg font-semibold mb-4">YOUR DOCUMENTS</h2>
        {documents.length === 0 ? (
          <p className="text-gray-400 text-center py-8">No documents uploaded yet</p>
        ) : (
          <div className="space-y-3">
            {documents.map((doc) => (
              <div key={doc.id} className="bg-gray-800 p-4 rounded-lg">
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-3 flex-1">
                    <span className="material-icons text-teal-400">
                      {doc.mime_type?.includes('pdf') ? 'picture_as_pdf' :
                        doc.mime_type?.includes('word') ? 'article' :
                          'description'}
                    </span>
                    <div className="flex-1">
                      {editingDocumentId === doc.id ? (
                        <div className="flex items-center space-x-2">
                          <input
                            type="text"
                            value={editingDocumentTitle}
                            onChange={(event) => onEditDocumentTitleChange(event.target.value)}
                            className="flex-1 bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white text-sm"
                            onKeyPress={(event) => {
                              if (event.key === 'Enter') {
                                onUpdateDocumentTitle(doc.id, editingDocumentTitle)
                              }
                              if (event.key === 'Escape') {
                                onCancelEditDocumentTitle()
                              }
                            }}
                            autoFocus
                          />
                          <button
                            onClick={() => onUpdateDocumentTitle(doc.id, editingDocumentTitle)}
                            className="text-green-400 hover:text-green-300 p-1"
                            title="Save"
                          >
                            <span className="material-icons text-sm">check</span>
                          </button>
                          <button
                            onClick={onCancelEditDocumentTitle}
                            className="text-gray-400 hover:text-gray-300 p-1"
                            title="Cancel"
                          >
                            <span className="material-icons text-sm">close</span>
                          </button>
                        </div>
                      ) : (
                        <div className="flex items-center space-x-2">
                          <p className="text-white font-medium flex-1">{doc.title || doc.original_filename}</p>
                          <button
                            onClick={() => onStartEditDocumentTitle(doc)}
                            className="text-gray-400 hover:text-gray-300 p-1"
                            title="Edit title"
                          >
                            <span className="material-icons text-sm">edit</span>
                          </button>
                        </div>
                      )}
                      <div className="flex items-center space-x-4 text-sm text-gray-400 mt-1">
                        <span>{(doc.file_size / 1024 / 1024).toFixed(2)} MB</span>
                        <span>•</span>
                        <span>Uploaded {new Date(doc.created_at).toLocaleDateString()}</span>
                        <span>•</span>
                        <span className={`px-2 py-1 rounded text-xs ${doc.is_processed === 'true'
                          ? 'bg-green-900 text-green-300'
                          : doc.is_processed === 'error'
                            ? 'bg-red-900 text-red-300'
                            : 'bg-yellow-900 text-yellow-300'
                          }`}>
                          {doc.is_processed === 'true' ? 'Processed' :
                            doc.is_processed === 'error' ? 'Error' :
                              'Processing...'}
                        </span>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center space-x-2">
                    <button
                      onClick={() => onDownloadDocument(doc.id, doc.original_filename)}
                      className="text-teal-400 hover:text-teal-300 p-2"
                      title="Download"
                    >
                      <span className="material-icons">download</span>
                    </button>
                    <button
                      onClick={() => onDeleteDocument(doc.id)}
                      className="text-red-400 hover:text-red-300 p-2"
                      title="Delete"
                    >
                      <span className="material-icons">delete</span>
                    </button>
                  </div>
                </div>

                {doc.content_text && doc.is_processed === 'true' && (
                  <div className="mt-3 pt-3 border-t border-gray-700">
                    <p className="text-sm text-gray-400 mb-2">Document Preview:</p>
                    <p className="text-xs text-gray-500 line-clamp-3">
                      {doc.content_text.substring(0, 200)}...
                    </p>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default DocumentsWorkspaceView
