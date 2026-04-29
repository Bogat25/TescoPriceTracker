import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { AppConfigService } from '../services/app-config.service';

// Ensures session cookies (if any are set by an upstream gateway or proxy)
// are always sent along with API requests, even if the API URL is hosted cross-origin.
export const authHttpInterceptor: HttpInterceptorFn = (request, next) => {
  const config = inject(AppConfigService);

  // If the request is going to our configured API/Gateway, ensure credentials are included
  if (request.url.startsWith(config.tescoApiBaseUrl)) {
    return next(request.clone({ withCredentials: true }));
  }
  
  return next(request);
};
