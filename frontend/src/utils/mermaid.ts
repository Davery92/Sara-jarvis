let mermaidPromise: Promise<typeof import('mermaid').default> | null = null

export async function loadMermaid() {
  if (!mermaidPromise) {
    mermaidPromise = import('mermaid').then((module) => module.default)
  }

  return mermaidPromise
}
