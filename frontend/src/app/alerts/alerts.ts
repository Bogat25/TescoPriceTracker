import { Component, OnInit, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { AlertsService, PriceAlert } from '../services/alerts.service';
import { HexIcon } from '../shared/hex-icon/hex-icon';
import { HexKpi }  from '../shared/hex-kpi/hex-kpi';
import { SecLabel } from '../shared/sec-label/sec-label';

@Component({
  selector: 'app-alerts',
  imports: [CommonModule, RouterLink, HexIcon, HexKpi, SecLabel],
  templateUrl: './alerts.html',
  styleUrl: './alerts.scss',
})
export class Alerts implements OnInit {
  private alertsApi = inject(AlertsService);

  readonly alerts  = signal<PriceAlert[]>([]);
  readonly loading = signal(true);
  readonly error   = signal('');

  readonly enabledCount   = computed(() => this.alerts().filter(a => a.enabled).length);
  readonly disabledCount  = computed(() => this.alerts().filter(a => !a.enabled).length);

  ngOnInit(): void {
    this.alertsApi.list().subscribe({
      next: (res) => {
        this.alerts.set(res.alerts || []);
        this.loading.set(false);
      },
      error: (err) => {
        if (err?.status === 401) {
          this.error.set('unauthorized');
        } else {
          this.error.set('unavailable');
        }
        this.loading.set(false);
      },
    });
  }

  remove(id: string): void {
    this.alertsApi.remove(id).subscribe({
      next: () => this.alerts.update((list) => list.filter((a) => a.id !== id)),
      error: () => this.error.set('Failed to delete alert.'),
    });
  }

  formatAlertDescription(a: PriceAlert): string {
    if (a.alertType === 'TARGET_PRICE') {
      return `Notify when price drops to or below ${a.targetPrice} Ft`;
    }
    return `Notify on ${a.dropPercentage}%+ drop from ${a.basePriceAtCreation} Ft`;
  }
}
