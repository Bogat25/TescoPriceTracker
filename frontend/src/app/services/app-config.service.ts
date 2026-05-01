import { Injectable } from '@angular/core';

/** Shape of the global injected by /runtime-config.js at page load. */
interface RuntimeConfig {
  tescoApiBaseUrl?: string;
  authBaseUrl?: string;
  authLoginUrl?: string;
  authLogoutUrl?: string;
  authUserinfoUrl?: string;
  authAccountUrl?: string;
}

declare global {
  interface Window {
    __APP_CONFIG__?: RuntimeConfig;
  }
}

const DEFAULT_TESCO_BASE = '/api/tesco';
const DEFAULT_AUTH_BASE = '/auth';
const DEFAULT_AUTH_LOGIN = '/auth/login';
const DEFAULT_AUTH_LOGOUT = '/auth/logout';
const DEFAULT_AUTH_USERINFO = '/auth/userinfo';
const DEFAULT_AUTH_ACCOUNT = '/auth/account';

/**
 * Reads deploy-time configuration injected by runtime-config.js.
 *
 * The Angular bundle is built once and identical across deployments — values
 * that need to vary per environment (e.g. the API domain) live in
 * window.__APP_CONFIG__, which nginx generates from env vars via
 * envsubst at container start. See frontend/runtime-config.template.js.
 */
@Injectable({ providedIn: 'root' })
export class AppConfigService {
  /** Base URL for product endpoints. Trailing slashes are stripped. */
  readonly tescoApiBaseUrl: string = this.normalize(
    window.__APP_CONFIG__?.tescoApiBaseUrl,
    DEFAULT_TESCO_BASE,
  );

  /** Base URL for authentication (Keycloak). Trailing slashes are stripped. */
  readonly authBaseUrl: string = this.normalize(
    window.__APP_CONFIG__?.authBaseUrl,
    DEFAULT_AUTH_BASE,
  );

  readonly authLoginUrl: string = this.normalize(
    window.__APP_CONFIG__?.authLoginUrl,
    DEFAULT_AUTH_LOGIN,
  );

  readonly authLogoutUrl: string = this.normalize(
    window.__APP_CONFIG__?.authLogoutUrl,
    DEFAULT_AUTH_LOGOUT,
  );

  readonly authUserinfoUrl: string = this.normalize(
    window.__APP_CONFIG__?.authUserinfoUrl,
    DEFAULT_AUTH_USERINFO,
  );

  readonly authAccountUrl: string = this.normalize(
    window.__APP_CONFIG__?.authAccountUrl,
    DEFAULT_AUTH_ACCOUNT,
  );

  private normalize(raw: string | undefined, defaultValue: string): string {
    const value = (raw ?? '').trim();
    if (!value || value.startsWith('${')) return defaultValue;
    return value.replace(/\/+$/, '');
  }
}
