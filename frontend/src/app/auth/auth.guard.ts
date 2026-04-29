import { inject } from '@angular/core';
import { CanActivateFn } from '@angular/router';
import { AuthService } from '../services/auth.service';

export const authGuard: CanActivateFn = async () => {
  const authService = inject(AuthService);

  const isLoggedIn = await authService.isLoggedIn();
  if (isLoggedIn) return true;

  authService.login(window.location.href);
  return false;
};
