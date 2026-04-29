import { HttpInterceptorFn } from '@angular/common/http';

// Every request to the gateway must carry credentials so the GavallerAuthCookie
// is sent. Requests to the local nginx proxy (/api/tesco/*) do not need this —
// they go to the same origin and carry no sensitive headers.
export const authHttpInterceptor: HttpInterceptorFn = (request, next) => {
  if (request.url.includes('gateway.gavaller.com')) {
    return next(request.clone({ withCredentials: true }));
  }
  return next(request);
};
