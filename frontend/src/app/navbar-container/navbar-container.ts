import { Component, OnDestroy, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { NavigationEnd, Router, RouterModule } from '@angular/router';
import { Subscription, filter } from 'rxjs';
import { AuthService } from '../services/auth.service';
import { ThemeService } from '../services/theme.service';

interface NavLink {
  label: string;
  path: string;
  authRequired?: boolean;
}

@Component({
  selector: 'app-navbar-container',
  imports: [CommonModule, RouterModule],
  templateUrl: './navbar-container.html',
  styleUrl: './navbar-container.scss',
})
export class NavbarContainer implements OnInit, OnDestroy {
  public themeService = inject(ThemeService);
  public authService = inject(AuthService);
  private router = inject(Router);
  private sub?: Subscription;

  links: NavLink[] = [
    { label: 'Home', path: '/' },
    { label: 'Search', path: '/search' },
    { label: 'Statistics', path: '/statistics' },
    { label: 'My Alerts', path: '/alerts', authRequired: true },
  ];

  ngOnInit(): void {
    this.authService.checkSession().subscribe();
    this.sub = this.router.events
      .pipe(filter((e) => e instanceof NavigationEnd))
      .subscribe(() => this.authService.checkSession().subscribe());
  }

  get userInitials(): string {
    const name = this.authService.userName();
    if (!name) return 'U';
    return name.substring(0, 2).toUpperCase();
  }

  accountSettings(): void {
    this.authService.account();
  }

  logout(): void {
    this.authService.logout();
  }

  ngOnDestroy(): void {
    this.sub?.unsubscribe();
  }
}
