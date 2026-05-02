import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { from, switchMap, catchError, EMPTY } from 'rxjs';
import { AuthTokenService } from '../services/auth-token.service';
import { AuthService } from '../services/auth.service';

/**
 * Attaches a Bearer token to requests targeting /api/alerts/.
 * On 401, clears auth state and redirects to login.
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
        authService.login(window.location.href);
        return EMPTY;
      }
      throw err;
    }),
  );
};
