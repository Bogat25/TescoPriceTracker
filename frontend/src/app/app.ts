import { Component, inject, OnInit } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { AuthService } from './services/auth.service';
import { Sidebar } from './sidebar/sidebar';
import { BeehiveBg } from './shared/beehive-bg/beehive-bg';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, Sidebar, BeehiveBg],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App implements OnInit {
  private authService = inject(AuthService);

  ngOnInit(): void {
    this.authService.checkSession().subscribe();
  }
}
