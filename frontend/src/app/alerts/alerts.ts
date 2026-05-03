import { Component, OnInit, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { AlertsService, PriceAlert } from '../services/alerts.service';
import { AuthService } from '../services/auth.service';
import { ProductsService, ProductSummary } from '../services/products.service';
import { TranslationService } from '../services/translation.service';
import { TranslatePipe } from '../shared/translate.pipe';
import { HexIcon } from '../shared/hex-icon/hex-icon';
import { HexKpi }  from '../shared/hex-kpi/hex-kpi';
import { SecLabel } from '../shared/sec-label/sec-label';

@Component({
  selector: 'app-alerts',
  imports: [CommonModule, RouterLink, HexIcon, HexKpi, SecLabel, TranslatePipe],
  templateUrl: './alerts.html',
  styleUrl: './alerts.scss',
})
export class Alerts implements OnInit {
  private alertsApi = inject(AlertsService);
  private productsApi = inject(ProductsService);
  readonly authService = inject(AuthService);
  readonly tl = inject(TranslationService);

  readonly alerts  = signal<PriceAlert[]>([]);
  readonly loading = signal(true);
  readonly error   = signal('');
  readonly emailEnabled = signal(true);
  readonly savingEmailPref = signal(false);

  /** Map of tpnc → product summary (name + current price). */
  readonly productMap = signal<Map<string, ProductSummary>>(new Map());

  readonly totalCount    = computed(() => this.alerts().length);
  readonly enabledCount  = computed(() => this.alerts().filter(a => a.enabled).length);
  readonly disabledCount = computed(() => this.alerts().filter(a => !a.enabled).length);

  /** Alerts sorted: enabled first, then disabled at the bottom. */
  readonly sortedAlerts = computed(() =>
    [...this.alerts()].sort((a, b) => {
      if (a.enabled === b.enabled) return 0;
      return a.enabled ? -1 : 1;
    })
  );

  /** Triggered: enabled alerts where the price condition is currently met. */
  readonly triggeredCount = computed(() => {
    const map = this.productMap();
    return this.alerts().filter(a => {
      if (!a.enabled) return false;
      const prod = map.get(a.productId);
      const price = prod?.currentPrice;
      if (price === undefined || price === null) return false;
      if (a.alertType === 'TARGET_PRICE' && a.targetPrice !== null) {
        return price <= a.targetPrice;
      }
      if (a.alertType === 'PERCENTAGE_DROP' && a.dropPercentage !== null && a.basePriceAtCreation !== null) {
        const threshold = a.basePriceAtCreation * (1 - a.dropPercentage / 100);
        return price <= threshold;
      }
      return false;
    }).length;
  });

  ngOnInit(): void {
    // Show login prompt immediately if not authenticated — no API call needed
    if (!this.authService.authenticated()) {
      this.error.set('unauthorized');
      this.loading.set(false);
      return;
    }
    this.alertsApi.list().subscribe({
      next: (res) => {
        const list = res.alerts || [];
        this.alerts.set(list);
        this.loading.set(false);
        this.loadProductInfo(list);
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
    // Load email preference in parallel
    this.alertsApi.getEmailPreference().subscribe({
      next: (prefs) => this.emailEnabled.set(prefs.emailEnabled),
      error: () => { /* keep default true */ },
    });
  }

  private loadProductInfo(alerts: PriceAlert[]): void {
    const ids = [...new Set(alerts.map(a => a.productId))];
    if (!ids.length) return;

    const calls = ids.map(id =>
      this.productsApi.get(id).pipe(catchError(() => of(null)))
    );
    forkJoin(calls).subscribe(results => {
      const map = new Map<string, ProductSummary>();
      results.forEach((p, i) => { if (p) map.set(ids[i], p); });
      this.productMap.set(map);
    });
  }

  /** Get product name from map, fallback to productId. */
  productName(a: PriceAlert): string {
    return this.productMap().get(a.productId)?.name || a.productId;
  }

  /** Get product image URL from map. */
  productImage(a: PriceAlert): string | undefined {
    return this.productMap().get(a.productId)?.imageUrl;
  }

  /** Get current price from map. */
  productPrice(a: PriceAlert): number | undefined {
    return this.productMap().get(a.productId)?.currentPrice;
  }

  /** Is this alert currently triggered (condition met)? */
  isTriggered(a: PriceAlert): boolean {
    if (!a.enabled) return false;
    const price = this.productPrice(a);
    if (price === undefined || price === null) return false;
    if (a.alertType === 'TARGET_PRICE' && a.targetPrice !== null) {
      return price <= a.targetPrice;
    }
    if (a.alertType === 'PERCENTAGE_DROP' && a.dropPercentage !== null && a.basePriceAtCreation !== null) {
      return price <= a.basePriceAtCreation * (1 - a.dropPercentage / 100);
    }
    return false;
  }

  /** Tesco Hungary product URL. */
  tescoUrl(tpnc: string): string {
    return `https://bevasarlas.tesco.hu/shop/en-HU/products/${tpnc}`;
  }

  toggle(a: PriceAlert): void {
    const newEnabled = !a.enabled;
    // Optimistic update — change the UI immediately without waiting for the API
    this.alerts.update(list =>
      list.map(x => x.id === a.id ? { ...x, enabled: newEnabled } : x)
    );
    this.alertsApi.toggle(a.id, newEnabled).subscribe({
      next: (updated) => {
        // Confirm with the server response
        this.alerts.update(list =>
          list.map(x => x.id === updated.id ? { ...x, enabled: updated.enabled } : x)
        );
      },
      error: () => {
        // Revert on failure — no reload needed
        this.alerts.update(list =>
          list.map(x => x.id === a.id ? { ...x, enabled: a.enabled } : x)
        );
        this.error.set('Could not update alert. Please try again.');
        setTimeout(() => this.error.set(''), 4000);
      },
    });
  }

  remove(id: string): void {
    this.alertsApi.remove(id).subscribe({
      next: () => this.alerts.update((list) => list.filter((a) => a.id !== id)),
      error: () => this.error.set('Failed to delete alert.'),
    });
  }

  toggleEmailEnabled(): void {
    const newVal = !this.emailEnabled();
    this.emailEnabled.set(newVal); // optimistic
    this.savingEmailPref.set(true);
    this.alertsApi.setEmailPreference(newVal).subscribe({
      next: (prefs) => {
        this.emailEnabled.set(prefs.emailEnabled);
        this.savingEmailPref.set(false);
      },
      error: () => {
        this.emailEnabled.set(!newVal); // revert
        this.savingEmailPref.set(false);
      },
    });
  }

  formatAlertDescription(a: PriceAlert): string {
    if (a.alertType === 'TARGET_PRICE') {
      return `Notify when price drops to or below ${a.targetPrice} Ft`;
    }
    return `Notify on ${a.dropPercentage}%+ drop from ${a.basePriceAtCreation} Ft`;
  }
}
