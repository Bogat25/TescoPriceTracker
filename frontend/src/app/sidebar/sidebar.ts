import { Component, OnInit, inject, signal, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router, NavigationEnd } from '@angular/router';
import { filter, Subscription, catchError, of } from 'rxjs';
import { AuthService } from '../services/auth.service';
import { ThemeService } from '../services/theme.service';
import { AlertsService } from '../services/alerts.service';
import { TranslationService } from '../services/translation.service';
import { TranslatePipe } from '../shared/translate.pipe';

interface NavItem {
  id: string;
  label: string;
  path: string;
  authRequired?: boolean;
  iconPath: string;
}

const NAV_ITEMS: NavItem[] = [
  {
    id: 'home',
    label: 'nav.dashboard',
    path: '/',
    iconPath: 'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
  },
  {
    id: 'search',
    label: 'nav.search',
    path: '/search',
    iconPath: 'M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z',
  },
  {
    id: 'products',
    label: 'nav.catalogue',
    path: '/products',
    iconPath: 'M4 6h16M4 10h16M4 14h16M4 18h16',
  },
  {
    id: 'statistics',
    label: 'nav.analytics',
    path: '/statistics',
    iconPath: 'M18 20V10M12 20V4M6 20v-6',
  },
  {
    id: 'alerts',
    label: 'nav.alerts',
    path: '/alerts',
    authRequired: true,
    iconPath: 'M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 0 1-3.46 0',
  },
];

@Component({
  selector: 'app-sidebar',
  imports: [CommonModule, RouterModule, TranslatePipe],
  templateUrl: './sidebar.html',
  styleUrl: './sidebar.scss',
})
export class Sidebar implements OnInit, OnDestroy {
  public auth    = inject(AuthService);
  public theme   = inject(ThemeService);
  public tl      = inject(TranslationService);
  private alerts = inject(AlertsService);
  private router = inject(Router);

  readonly navItems = NAV_ITEMS;
  readonly alertCount = signal(0);
  readonly userMenuOpen = signal(false);
  activeRoute = signal('/');

  private routerSub?: Subscription;

  get userInitials(): string {
    const name = this.auth.userName();
    if (!name) return 'U';
    return name.substring(0, 2).toUpperCase();
  }

  ngOnInit(): void {
    this.activeRoute.set(this.router.url);
    this.routerSub = this.router.events
      .pipe(filter(e => e instanceof NavigationEnd))
      .subscribe(e => this.activeRoute.set((e as NavigationEnd).urlAfterRedirects));

    if (this.auth.authenticated()) {
      this.loadAlertCount();
    }
  }

  private loadAlertCount(): void {
    this.alerts.list().pipe(catchError(() => of({ alerts: [] }))).subscribe(res => {
      this.alertCount.set(res.alerts?.length ?? 0);
    });
  }

  isActive(path: string): boolean {
    const url = this.activeRoute();
    if (path === '/') return url === '/' || url === '';
    return url.startsWith(path);
  }

  toggleTheme(): void {
    this.theme.toggleTheme();
  }

  toggleUserMenu(): void {
    this.userMenuOpen.update(v => !v);
  }

  closeUserMenu(): void {
    this.userMenuOpen.set(false);
  }

  login(): void  { this.auth.login(); }
  logout(): void { this.closeUserMenu(); this.auth.logout(); }
  account(): void { this.closeUserMenu(); this.auth.account(); }

  ngOnDestroy(): void {
    this.routerSub?.unsubscribe();
  }

  /** 3×3 hex decoration data: 3 columns, each col shifted down for col 1 */
  readonly hexDecoration = [0, 1, 2].flatMap(col =>
    [0, 1, 2].map(row => ({ col, row, opacity: 0.15 + (col * 3 + row) * 0.06 }))
  );
}
