import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { from, switchMap, catchError, EMPTY } from 'rxjs';
import { AuthTokenService } from '../services/auth-token.service';

/**
 * Attaches a Bearer token to requests targeting /api/alerts/.
 * On 401, clears auth state and redirects to login.
 */
export const alertsAuthInterceptor: HttpInterceptorFn = (request, next) => {
  if (!request.url.includes('/api/alerts')) {
    return next(request);
  }

  const tokenService = inject(AuthTokenService);

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
      // If getting the token itself failed (401 from /auth/token), redirect to login
      if (err?.status === 401) {
        tokenService.clear();
        const returnUrl = encodeURIComponent(window.location.href);
        window.location.href = `/auth/login?returnUrl=${returnUrl}`;
        return EMPTY;
      }
      throw err;
    }),
  );
};
