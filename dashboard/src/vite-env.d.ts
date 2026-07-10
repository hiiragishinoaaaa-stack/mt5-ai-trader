/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** settings_server.py のベースURL。既定 http://localhost:8787 */
  readonly VITE_SETTINGS_API_URL?: string;
  /** settings_server.py 側でSETTINGS_API_TOKENを設定した場合のみ必要。 */
  readonly VITE_SETTINGS_API_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
