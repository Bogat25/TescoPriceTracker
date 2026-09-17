import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { throwError } from 'rxjs';
import { switchMap } from 'rxjs/operators';
import { AlertType, AlertsService, CreateAlertRequest } from '../../services/alerts.service';
import { AuthService } from '../../services/auth.service';
import { Offer } from '../../services/catalog.service';
import { StoresService } from '../../services/stores.service';
import { TranslationService } from '../../services/translation.service';
import { TranslatePipe } from '../translate.pipe';
import { storeAccent } from '../store-accent';

export type AlertFormError = 'alertform.err.stores' | 'alertform.err.target' | 'alertform.err.below' | 'alertform.err.pct' | 'alertform.err.base';

/** Lowest current price across the chosen stores' offers. */
export function lowestPrice(offers: Offer[], stores: string[]): number | null {
  const prices = offers
    .filter((o) => stores.includes(o.store) && o.effective_price !== null)
    .map((o) => o.effective_price as number);
  return prices.length ? Math.min(...prices) : null;
}

/**
 * The alert request for a product row, or the reason it cannot be sent.
 * A group alert names its stores; an offer alert watches its own store.
 */
export function buildAlertRequest(
  target: string,
  offers: Offer[],
  stores: string[],
  type: AlertType,
  value: number | null,
): CreateAlertRequest | AlertFormError {
  const isGroup = target.startsWith('g:');
  const watched = isGroup ? stores : offers.filter((o) => o.ref === target).map((o) => o.store);
  if (!watched.length) return 'alertform.err.stores';
  const current = lowestPrice(offers, watched);
  const base = isGroup ? { target, stores: watched } : { target };
  if (type === 'TARGET_PRICE') {
    if (value === null || Number.isNaN(value) || value <= 0) return 'alertform.err.target';
    if (current !== null && value >= current) return 'alertform.err.below';
    return { ...base, alertType: 'TARGET_PRICE', targetPrice: value };
  }
  if (value === null || Number.isNaN(value) || value <= 0 || value > 100) return 'alertform.err.pct';
  if (current === null || current <= 0) return 'alertform.err.base';
  return { ...base, alertType: 'PERCENTAGE_DROP', dropPercentage: value, basePriceAtCreation: current };
}

/** Price alert for a product in the stores the user ticks. */
@Component({
  selector: 'app-store-alert-form',
  imports: [FormsModule, TranslatePipe],
  templateUrl: './store-alert-form.html',
  styleUrl: './store-alert-form.scss',
})
export class StoreAlertForm {
  /** Offer ref or group ID. */
  readonly target = input.required<string>();
  readonly offers = input.required<Offer[]>();

  readonly auth = inject(AuthService);
  readonly stores = inject(StoresService);
  private alertsApi = inject(AlertsService);
  private tl = inject(TranslationService);

  type: AlertType = 'TARGET_PRICE';
  value: number | null = null;
  readonly chosen = signal<string[]>([]);
  readonly saving = signal(false);
  readonly message = signal('');
  readonly saved = signal(false);

  readonly isGroup = computed(() => this.target().startsWith('g:'));
  readonly offerStores = computed(() => [...new Set(this.offers().map((o) => o.store))]);
  readonly current = computed(() =>
    lowestPrice(this.offers(), this.isGroup() ? this.chosen() : this.offerStores()),
  );

  constructor() {
    // Every store selling the product starts ticked.
    effect(() => this.chosen.set(this.offerStores()));
  }

  accent(store: string): string {
    return storeAccent(store);
  }

  toggleStore(store: string): void {
    this.chosen.update((list) => (list.includes(store) ? list.filter((s) => s !== store) : [...list, store]));
  }

  save(): void {
    this.message.set('');
    this.saved.set(false);
    const req = buildAlertRequest(this.target(), this.offers(), this.chosen(), this.type, this.value);
    if (typeof req === 'string') {
      this.message.set(this.tl.t(req));
      return;
    }
    this.saving.set(true);
    this.auth
      .checkSession()
      .pipe(switchMap((user) => (user ? this.alertsApi.create(req) : throwError(() => ({ status: 401 })))))
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.saved.set(true);
          this.message.set(this.tl.t('alertform.saved'));
          this.value = null;
        },
        error: (err) => {
          this.saving.set(false);
          const unauthorized = err?.status === 401 || err?.status === 403;
          this.message.set(unauthorized ? this.tl.t('alertform.err.login') : err?.error?.detail || this.tl.t('alertform.err.save'));
        },
      });
  }
}
