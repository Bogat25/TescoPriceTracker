import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

interface TokenResponse {
  access_token: string;
  expires_in: number;
}

@Injectable({ providedIn: 'root' })
export class AuthTokenService {
  private http = inject(HttpClient);

  private cachedToken: string | null = null;
  private expiresAt = 0;

  async getToken(): Promise<string> {
    const now = Date.now();
    // Return cached if still valid (with 30s buffer)
    if (this.cachedToken && now < this.expiresAt - 30_000) {
      return this.cachedToken;
    }

    const res = await firstValueFrom(
      this.http.get<TokenResponse>('/auth/token', { withCredentials: true }),
    );
    this.cachedToken = res.access_token;
    this.expiresAt = now + res.expires_in * 1000;
    return this.cachedToken;
  }

  clear(): void {
    this.cachedToken = null;
    this.expiresAt = 0;
  }
}
