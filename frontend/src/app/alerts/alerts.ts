import { Component, OnInit, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { AlertsService, PriceAlert } from '../services/alerts.service';
import { AuthService } from '../services/auth.service';
import { AlertProduct, AlertProductsService, alertLink, alertStores, alertTarget, watchedOffers } from '../services/alert-products.service';
import { StoresService } from '../services/stores.service';
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
  private alertProducts = inject(AlertProductsService);
  readonly stores = inject(StoresService);
  readonly authService = inject(AuthService);
  readonly tl = inject(TranslationService);

  readonly alerts  = signal<PriceAlert[]>([]);
  readonly loading = signal(true);
  readonly error   = signal('');
  readonly emailEnabled = signal(true);
  readonly savingEmailPref = signal(false);

  /** Alert target → watched product with its store offers. */
  readonly productMap = signal<Map<string, AlertProduct>>(new Map());

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
    this.productMap();
    return this.alerts().filter((a) => this.isTriggered(a)).length;
  });

  ngOnInit(): void {
    // Do not read the initial signal synchronously: AppComponent's /userinfo
    // request is commonly still in flight while this routed component starts.
    // Waiting for the shared session observable prevents a signed-in user from
    // being permanently rendered as anonymous.
    this.authService.checkSession().subscribe((user) => {
      if (!user) {
        this.error.set('unauthorized');
        this.loading.set(false);
        return;
      }
      this.loadAlerts();
    });
  }

  private loadAlerts(): void {
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
    this.stores.load().subscribe();
    this.alertProducts.resolve(alerts).subscribe((products) => this.productMap.set(products));
  }

  link(a: PriceAlert): string[] {
    return alertLink(a);
  }

  /** Product name, falling back to the watched reference. */
  productName(a: PriceAlert): string {
    return this.productMap().get(alertTarget(a))?.name || a.productId;
  }

  productImage(a: PriceAlert): string | undefined {
    return this.productMap().get(alertTarget(a))?.imageUrl ?? undefined;
  }

  /** Lowest current price across the watched stores. */
  productPrice(a: PriceAlert): number | undefined {
    return watchedOffers(a, this.productMap().get(alertTarget(a)))[0]?.effective_price ?? undefined;
  }

  /** Store page of the cheapest watched offer. */
  storeUrl(a: PriceAlert): string | null {
    return watchedOffers(a, this.productMap().get(alertTarget(a)))[0]?.url ?? null;
  }

  storeNames(a: PriceAlert): string {
    return alertStores(a).map((id) => this.stores.name(id)).join(', ');
  }

  /** Is this alert currently triggered (condition met)? */
  isTriggered(a: PriceAlert): boolean {
    if (!a.enabled || a.paused) return false;
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
