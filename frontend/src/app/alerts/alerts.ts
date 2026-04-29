import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { AlertsService, PriceAlert } from '../services/alerts.service';

@Component({
  selector: 'app-alerts',
  imports: [CommonModule, RouterLink],
  templateUrl: './alerts.html',
  styleUrl: './alerts.scss',
})
export class Alerts implements OnInit {
  private alertsApi = inject(AlertsService);

  readonly alerts = signal<PriceAlert[]>([]);
  readonly loading = signal(true);
  readonly error = signal('');

  ngOnInit(): void {
    this.alertsApi.list().subscribe({
      next: (res) => {
        this.alerts.set(res.alerts || []);
        this.loading.set(false);
      },
      error: () => {
        // No backend for alerts yet — show the informational placeholder.
        this.error.set('unavailable');
        this.loading.set(false);
      },
    });
  }

  remove(id: number): void {
    this.alertsApi.remove(id).subscribe({
      next: () => this.alerts.update((list) => list.filter((a) => a.id !== id)),
      error: () => this.error.set('unavailable'),
    });
  }
}
