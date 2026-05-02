import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { from, switchMap, catchError, throwError } from 'rxjs';
import { AuthTokenService } from '../services/auth-token.service';
import { AuthService } from '../services/auth.service';

/**
 * Attaches a Bearer token to /api/alerts/* requests.
 *
 * On 401 we DO NOT auto-redirect to login. Two cases produce a 401:
 *   (a) No session — the gateway's /token call would have already failed (also
 *       a 401 from a *different* origin) and we'd see it here. In that case
 *       checkSession() will report unauthenticated, and the alerts page itself
 *       (or the route guard on next navigation) routes to login.
 *   (b) Session is valid but the alert-service rejected the JWT (issuer/azp/
 *       signature mismatch — see alert-service/auth.py). Redirecting to login
 *       in this case produces an infinite loop: gateway honors the cookie,
 *       bounces straight back, SPA reloads, 401 again, login again…
 *
 * So we just propagate the error and let the caller render a "couldn't load"
 * state. We refresh AuthService's cache so a stale "authenticated" signal
 * gets re-checked on the next interaction.
 */
export const alertsAuthInterceptor: HttpInterceptorFn = (request, next) => {
  if (!request.url.includes('/api/alerts')) {
    return next(request);
  }

  const tokenService = inject(AuthTokenService);
  const authService = inject(AuthService);

  return from(tokenService.getToken()).pipe(
    switchMap((token) =>
      next(
        request.clone({
          setHeaders: { Authorization: `Bearer ${token}` },
          withCredentials: true,
        }),
      ),
    ),
    catchError((err) => {
      if (err?.status === 401) {
        tokenService.clear();
        authService.invalidateSession();
      }
      return throwError(() => err);
    }),
  );
};
