import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { BehaviorSubject, Observable, firstValueFrom, of } from 'rxjs';
import { catchError, tap } from 'rxjs/operators';

import { AppConfigService } from './app-config.service';

export interface Claim {
  Type: string;
  Value: string;
}

export interface GatewayUser {
  Name: string;
  Claims: Claim[];
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private http = inject(HttpClient);
  private config = inject(AppConfigService);

  // Use the auth base URL for login/logout/userinfo (separate from product API)
  private get authBaseUrl() {
    return this.config.authBaseUrl;
  }

  readonly authenticated = signal(false);
  readonly loadingAuthState = signal(false);
  readonly userName = signal<string | null>(null);
  readonly userId = signal<string | null>(null);

  private userSubject = new BehaviorSubject<GatewayUser | null>(null);
  readonly user$ = this.userSubject.asObservable();

  checkSession(): Observable<GatewayUser | null> {
    this.loadingAuthState.set(true);
    return this.http
      .get<GatewayUser>(`${this.authBaseUrl}/userinfo`, { withCredentials: true })
      .pipe(
        tap((user) => {
          this.authenticated.set(true);
          this.userName.set(user.Name);
          const sub = user.Claims?.find((c) => c.Type === 'sub')?.Value ?? null;
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
          return of(null);
        }),
      );
  }

  async isLoggedIn(): Promise<boolean> {
    const user = await firstValueFrom(this.checkSession());
    return !!user;
  }

  // Top-level navigation — do not use fetch/XHR for these.
  login(returnUrl: string = window.location.href): void {
    window.location.href = `${this.authBaseUrl}/login?returnUrl=${encodeURIComponent(returnUrl)}`;
  }

  logout(returnUrl: string = window.location.origin): void {
    window.location.href = `${this.authBaseUrl}/logout?returnUrl=${encodeURIComponent(returnUrl)}`;
  }
}
