/// <reference types="svelte" />
/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Default bot API base URL baked at build time. Overridable at runtime in Settings. */
  readonly VITE_BOT_API_URL?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
