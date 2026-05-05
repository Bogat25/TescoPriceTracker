import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { BehaviorSubject, Observable, firstValueFrom, of } from 'rxjs';
import { catchError, shareReplay, tap } from 'rxjs/operators';

import { AppConfigService } from './app-config.service';

export interface Claim {
  type: string;   // ASP.NET Core minimal API serialises to camelCase
  value: string;
}

export interface GatewayUser {
  name: string;          // camelCase from gateway JSON
  sub?: string | null;
  email?: string | null;
  claims: Claim[];
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private http = inject(HttpClient);
  private config = inject(AppConfigService);

  // Use the auth base URL for login/logout/userinfo (separate from product API)
  private get authBaseUrl() {
    return this.config.authBaseUrl;
  }

  private get authLoginUrl() {
    return this.config.authLoginUrl;
  }

  private get authLogoutUrl() {
    return this.config.authLogoutUrl;
  }

  private get authUserinfoUrl() {
    return this.config.authUserinfoUrl;
  }

  private get authAccountUrl() {
    return this.config.authAccountUrl;
  }

  private get authSwitchAccountUrl() {
    return this.config.authSwitchAccountUrl;
  }

  get loginUrl() {
    return this.config.authLoginUrl;
  }

  readonly authenticated = signal(false);
  readonly loadingAuthState = signal(false);
  readonly userName = signal<string | null>(null);
  readonly userId = signal<string | null>(null);

  private userSubject = new BehaviorSubject<GatewayUser | null>(null);
  readonly user$ = this.userSubject.asObservable();

  // Dedup concurrent /userinfo calls and reuse the result for a short window so
  // bootstrap + navbar + route guard + page components don't each fire their own.
  private static readonly SESSION_TTL_MS = 30_000;
  private sessionCache$: Observable<GatewayUser | null> | null = null;
  private sessionCacheExpiresAt = 0;

  checkSession(force = false): Observable<GatewayUser | null> {
    const now = Date.now();
    if (!force && this.sessionCache$ && now < this.sessionCacheExpiresAt) {
      return this.sessionCache$;
    }

    this.loadingAuthState.set(true);
    this.sessionCache$ = this.http
      .get<GatewayUser>(this.authUserinfoUrl, { withCredentials: true })
      .pipe(
        tap((user) => {
          this.authenticated.set(true);
          this.userName.set(user.name);
          // Try top-level sub first (gateway v2+), then fall back to claims array.
          // Handles both MapInboundClaims=false ("sub" type) and legacy sessions
          // where ASP.NET Core remaps sub → WS-Fed nameidentifier URI.
          const sub =
            user.sub
            ?? user.claims?.find(c => c.type === 'sub')?.value
            ?? user.claims?.find(c => c.type.endsWith('/nameidentifier'))?.value
            ?? null;
          this.userId.set(sub);
          this.userSubject.next(user);
          this.loadingAuthState.set(false);
        }),
        catchError(() => {
          this.authenticated.set(false);
          this.userName.set(null);
          this.userId.set(null);
          this.userSubject.next(null);
          this.loadingAuthState.set(false);
          // Negative results are also cached for the same TTL — otherwise an
          // anonymous page load would re-spam /userinfo on every component init.
          return of(null);
        }),
        shareReplay({ bufferSize: 1, refCount: false }),
      );
    this.sessionCacheExpiresAt = now + AuthService.SESSION_TTL_MS;
    return this.sessionCache$;
  }

  invalidateSession(): void {
    this.sessionCache$ = null;
    this.sessionCacheExpiresAt = 0;
  }

  async isLoggedIn(): Promise<boolean> {
    const user = await firstValueFrom(this.checkSession());
    return !!user;
  }

  // Top-level navigation — do not use fetch/XHR for these.
  login(returnUrl: string = window.location.href): void {
    this.invalidateSession();
    const sep = this.authLoginUrl.includes('?') ? '&' : '?';
    window.location.href = `${this.authLoginUrl}${sep}returnUrl=${encodeURIComponent(returnUrl)}`;
  }

  logout(returnUrl: string = window.location.origin): void {
    this.invalidateSession();
    const sep = this.authLogoutUrl.includes('?') ? '&' : '?';
    window.location.href = `${this.authLogoutUrl}${sep}returnUrl=${encodeURIComponent(returnUrl)}`;
  }

  account(): void {
    window.location.href = this.authAccountUrl;
  }

  /**
   * Sign out the current user then force a fresh credential prompt.
   * Uses the dedicated /switch-account gateway endpoint which (1) invalidates
   * the server-side session and Keycloak session, and (2) adds prompt=login
   * to the subsequent OIDC challenge so Keycloak cannot silently re-use the
   * existing session.
   */
  switchAccount(): void {
    this.invalidateSession();
    const sep = this.authSwitchAccountUrl.includes('?') ? '&' : '?';
    window.location.href = `${this.authSwitchAccountUrl}${sep}returnUrl=${encodeURIComponent(window.location.href)}`;
  }
}
