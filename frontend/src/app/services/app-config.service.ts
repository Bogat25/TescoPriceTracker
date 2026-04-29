import { Injectable } from '@angular/core';

/** Shape of the global injected by /runtime-config.js at page load. */
interface RuntimeConfig {
  tescoApiBaseUrl?: string;
}

declare global {
  interface Window {
    __APP_CONFIG__?: RuntimeConfig;
  }
}

const DEFAULT_BASE = '/api/tesco';

/**
 * Reads deploy-time configuration injected by runtime-config.js.
 *
 * The Angular bundle is built once and identical across deployments — values
 * that need to vary per environment (e.g. the API domain) live in
 * window.__APP_CONFIG__, which nginx generates from TESCO_API_BASE_URL via
 * envsubst at container start. See frontend/runtime-config.template.js.
 */
@Injectable({ providedIn: 'root' })
export class AppConfigService {
  /** Base URL for product endpoints. Trailing slashes are stripped. */
  readonly tescoApiBaseUrl: string = this.normalize(
    window.__APP_CONFIG__?.tescoApiBaseUrl,
  );

  private normalize(raw: string | undefined): string {
    const value = (raw ?? '').trim();
    if (!value || value.startsWith('${')) return DEFAULT_BASE; // unsubstituted template
    return value.replace(/\/+$/, '');
  }
}
