import { Component, inject, OnInit, signal } from '@angular/core';
import { RouterOutlet, RouterLink, RouterLinkActive } from '@angular/router';
import { AuthService } from './services/auth.service';
import { ThemeService } from './services/theme.service';
import { TranslationService } from './services/translation.service';
import { Sidebar } from './sidebar/sidebar';
import { BeehiveBg } from './shared/beehive-bg/beehive-bg';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, Sidebar, BeehiveBg],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App implements OnInit {
  public authService  = inject(AuthService);
  public themeService = inject(ThemeService);
  public tl           = inject(TranslationService);

  readonly mobileMenuOpen = signal(false);

  ngOnInit(): void {
    this.authService.checkSession().subscribe();
  }

  mobileAccount(): void {
    if (this.authService.authenticated()) {
      this.mobileMenuOpen.set(true);
    } else {
      this.authService.login();
    }
  }

  closeMobileMenu(): void { this.mobileMenuOpen.set(false); }

  mobileLogout(): void {
    this.closeMobileMenu();
    this.authService.logout();
  }

  mobileAccountSettings(): void {
    this.closeMobileMenu();
    this.authService.account();
  }
}
