import { useCallback, useState } from 'react'
import { APP_CONFIG } from '../config'

interface ConfirmDialogConfig {
  title: string
  message: string
  confirmLabel?: string
  tone?: 'danger' | 'neutral'
  action: () => Promise<void> | void
}

interface UseDocumentWorkspaceOptions {
  onShowToast: (message: string, type?: string) => void
  onConfirm: (config: ConfirmDialogConfig) => void
}

export function useDocumentWorkspace({
  onShowToast,
  onConfirm,
}: UseDocumentWorkspaceOptions) {
  const [documents, setDocuments] = useState<any[]>([])
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [editingDocumentId, setEditingDocumentId] = useState<string | number | null>(null)
  const [editingDocumentTitle, setEditingDocumentTitle] = useState('')

  const loadDocuments = useCallback(async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/documents`, {
        credentials: 'include',
      })
      if (response.ok) {
        const documentsData = await response.json()
        setDocuments(documentsData)
      }
    } catch (error) {
      console.error('Failed to load documents:', error)
    }
  }, [])

  const uploadDocument = useCallback(async (file: File) => {
    if (!file) return

    setUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)

      const response = await fetch(`${APP_CONFIG.apiUrl}/documents`, {
        method: 'POST',
        body: formData,
        credentials: 'include',
      })

      if (response.ok) {
        const newDocument = await response.json()
        setDocuments((prev) => [newDocument, ...prev])
        setSelectedFile(null)
        onShowToast('Document uploaded successfully!', 'success')
      } else {
        const error = await response.json()
        onShowToast(error.detail || 'Failed to upload document', 'error')
      }
    } catch (error) {
      console.error('Upload error:', error)
      onShowToast('Failed to upload document', 'error')
    } finally {
      setUploading(false)
    }
  }, [onShowToast])

  const downloadDocument = useCallback(async (documentId: string, filename: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/documents/${documentId}/file`, {
        credentials: 'include',
      })

      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.style.display = 'none'
        link.href = url
        link.download = filename
        document.body.appendChild(link)
        link.click()
        window.URL.revokeObjectURL(url)
        document.body.removeChild(link)
      } else {
        onShowToast('Failed to download document', 'error')
      }
    } catch (error) {
      console.error('Download error:', error)
      onShowToast('Failed to download document', 'error')
    }
  }, [onShowToast])

  const executeDeleteDocument = useCallback(async (documentId: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/documents/${documentId}`, {
        method: 'DELETE',
        credentials: 'include',
      })

      if (response.ok) {
        setDocuments((prev) => prev.filter((doc) => doc.id !== documentId))
        onShowToast('Document deleted successfully', 'success')
      } else {
        onShowToast('Failed to delete document', 'error')
      }
    } catch (error) {
      console.error('Delete error:', error)
      onShowToast('Failed to delete document', 'error')
    }
  }, [onShowToast])

  const deleteDocument = useCallback((documentId: string) => {
    onConfirm({
      title: 'Delete document',
      message: 'Are you sure you want to delete this document? This action cannot be undone.',
      confirmLabel: 'Delete',
      tone: 'danger',
      action: () => executeDeleteDocument(documentId),
    })
  }, [executeDeleteDocument, onConfirm])

  const updateDocumentTitle = useCallback(async (documentId: string, newTitle: string) => {
    if (!newTitle.trim()) return

    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/documents/${documentId}?title=${encodeURIComponent(newTitle)}`,
        {
          method: 'PUT',
          credentials: 'include',
        },
      )

      if (response.ok) {
        const updatedDocument = await response.json()
        setDocuments((prev) => prev.map((doc) => (
          doc.id === documentId ? updatedDocument : doc
        )))
        setEditingDocumentId(null)
        setEditingDocumentTitle('')
        onShowToast('Document title updated successfully', 'success')
      } else {
        onShowToast('Failed to update document title', 'error')
      }
    } catch (error) {
      console.error('Update error:', error)
      onShowToast('Failed to update document title', 'error')
    }
  }, [onShowToast])

  const startEditDocumentTitle = useCallback((doc: any) => {
    setEditingDocumentId(doc.id)
    setEditingDocumentTitle(doc.title || doc.original_filename)
  }, [])

  const cancelEditDocumentTitle = useCallback(() => {
    setEditingDocumentId(null)
    setEditingDocumentTitle('')
  }, [])

  return {
    documents,
    selectedFile,
    setSelectedFile,
    uploading,
    editingDocumentId,
    editingDocumentTitle,
    setEditingDocumentTitle,
    loadDocuments,
    uploadDocument,
    downloadDocument,
    deleteDocument,
    updateDocumentTitle,
    startEditDocumentTitle,
    cancelEditDocumentTitle,
  }
}
