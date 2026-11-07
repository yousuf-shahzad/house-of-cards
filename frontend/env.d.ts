/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "1" serves the labelled synthetic fixture instead of calling the backend. */
  readonly VITE_API_MOCK?: string;
}
