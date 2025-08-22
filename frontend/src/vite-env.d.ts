/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string
  readonly VITE_ASSISTANT_NAME?: string
  readonly VITE_DOMAIN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}