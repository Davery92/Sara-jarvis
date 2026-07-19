/**
 * Surface types — mirror of backend app/schemas/surface.py (closed vocabulary).
 */

export interface SurfaceModel {
  id: string
  user_id: string
  conversation_id: string | null
  title: string
  surface_type: string
  spec: SurfaceSpec
  state: SurfaceState
  status: 'active' | 'torn_down' | 'expired'
  version: number
  expires_at: string | null
  created_at: string
  updated_at: string
}

export interface SurfaceSpec {
  components: SurfaceComponent[]
}

export type SurfaceState = Record<string, any>

export type SurfaceComponent =
  | MarkdownComponent
  | ChecklistComponent
  | StepsComponent
  | TimerComponent
  | FileListComponent
  | TableComponent
  | FormComponent
  | ButtonsComponent
  | ProgressComponent

export interface MarkdownComponent {
  type: 'markdown'
  text: string
}

export interface ChecklistItem {
  id: string
  label: string
  checked?: boolean
}
export interface ChecklistComponent {
  type: 'checklist'
  id: string
  items: ChecklistItem[]
  notify?: boolean
}

export interface StepItem {
  id: string
  text: string
  done?: boolean
}
export interface StepsComponent {
  type: 'steps'
  id: string
  steps: StepItem[]
  notify?: boolean
}

export interface TimerComponent {
  type: 'timer'
  id: string
  label?: string
  duration_seconds: number
  notify?: boolean
}

export interface FileEntry {
  name: string
  artifact_id?: string
  job_id?: string
  filename?: string
  size_bytes?: number
  mime?: string
}
export interface FileListComponent {
  type: 'file_list'
  id: string
  files: FileEntry[]
}

export interface TableColumn {
  key: string
  title: string
}
export interface TableComponent {
  type: 'table'
  id: string
  columns: TableColumn[]
  rows: Record<string, any>[]
}

export interface FormField {
  id: string
  label: string
  kind?: 'text' | 'number' | 'textarea' | 'select' | 'checkbox'
  options?: string[]
  value?: any
  placeholder?: string
}
export interface FormComponent {
  type: 'form'
  id: string
  fields: FormField[]
  submit_label?: string
  notify?: boolean
}

export interface ButtonSpec {
  id: string
  label: string
  style?: 'default' | 'primary' | 'danger'
  notify?: boolean
}
export interface ButtonsComponent {
  type: 'buttons'
  id: string
  buttons: ButtonSpec[]
}

export interface ProgressComponent {
  type: 'progress'
  id: string
  value?: number
  max?: number
  label?: string
}

// SSE command shape (mirror of backend surface_command)
export interface SurfaceCommand {
  surface_command: 'open' | 'update' | 'close'
  surface_id: string
  surface?: SurfaceModel
}

export interface SurfaceEventPayload {
  component_id: string
  event: 'check' | 'step' | 'submit' | 'click' | 'set'
  value?: Record<string, any>
}
