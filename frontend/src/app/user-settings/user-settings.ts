import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterLink } from '@angular/router';
import { AuthService } from '../services/auth.service';

@Component({
  selector: 'app-user-settings',
  imports: [CommonModule, RouterLink],
  templateUrl: './user-settings.html',
  styleUrl: './user-settings.scss',
})
export class UserSettings implements OnInit {
  private auth = inject(AuthService);
  private router = inject(Router);

  readonly loading = signal(true);
  readonly userName = signal('');
  readonly userId = signal('');

  ngOnInit(): void {
    this.auth.checkSession().subscribe((user) => {
      if (!user) {
        this.auth.login(window.location.href);
        return;
      }
      this.userName.set(user.name);
      const sub = user.sub
        ?? user.claims?.find((c) => c.type === 'sub')?.value
        ?? user.claims?.find((c) => c.type.endsWith('/nameidentifier'))?.value
        ?? '';
      this.userId.set(sub);
      this.loading.set(false);
    });
  }

  logout(): void {
    this.auth.logout();
  }

  switchAccount(): void {
    this.auth.switchAccount();
  }
}
