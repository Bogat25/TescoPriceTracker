import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { AppConfigService } from './app-config.service';

interface TokenResponse {
  access_token: string;
  expires_in: number;
}

@Injectable({ providedIn: 'root' })
export class AuthTokenService {
  private http = inject(HttpClient);
  private config = inject(AppConfigService);

  private cachedToken: string | null = null;
  private expiresAt = 0;
  private inFlight: Promise<string> | null = null;

  async getToken(): Promise<string> {
    const now = Date.now();
    // Return cached if still valid (with 30s buffer)
    if (this.cachedToken && now < this.expiresAt - 30_000) {
      return this.cachedToken;
    }

    if (this.inFlight) return this.inFlight;

    this.inFlight = (async () => {
      const res = await firstValueFrom(
        this.http.get<TokenResponse>(this.config.authTokenUrl, { withCredentials: true }),
      );
      if (!res.access_token || res.expires_in <= 0) {
        throw new Error('Authentication gateway returned an expired access token');
      }
      this.cachedToken = res.access_token;
      this.expiresAt = Date.now() + res.expires_in * 1000;
      return this.cachedToken;
    })();

    try {
      return await this.inFlight;
    } finally {
      this.inFlight = null;
    }
  }

  clear(): void {
    this.cachedToken = null;
    this.expiresAt = 0;
    this.inFlight = null;
  }
}
