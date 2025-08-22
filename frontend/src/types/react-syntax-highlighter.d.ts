declare module 'react-syntax-highlighter' {
  import { ComponentType } from 'react'
  
  export interface SyntaxHighlighterProps {
    language?: string
    style?: any
    PreTag?: string
    children: string
    [key: string]: any
  }
  
  const SyntaxHighlighter: ComponentType<SyntaxHighlighterProps>
  export default SyntaxHighlighter
}

declare module 'react-syntax-highlighter/dist/esm/styles/prism' {
  export const oneDark: any
  export const oneLight: any
}

declare module 'react-syntax-highlighter/dist/esm/styles/prism/one-dark' {
  const oneDark: any
  export default oneDark
}