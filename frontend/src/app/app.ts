import { Component, inject, OnInit } from '@angular/core';
import { RouterOutlet, RouterLink, RouterLinkActive } from '@angular/router';
import { AuthService } from './services/auth.service';
import { Sidebar } from './sidebar/sidebar';
import { BeehiveBg } from './shared/beehive-bg/beehive-bg';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, Sidebar, BeehiveBg],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App implements OnInit {
  private authService = inject(AuthService);

  ngOnInit(): void {
    this.authService.checkSession().subscribe();
  }

  mobileAccount(): void {
    if (this.authService.authenticated()) {
      this.authService.account();
    } else {
      this.authService.login();
    }
  }
}
