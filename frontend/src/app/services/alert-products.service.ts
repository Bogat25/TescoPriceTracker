import { Injectable, inject } from '@angular/core';
import { Observable, forkJoin, of } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { PriceAlert } from './alerts.service';
import { CatalogService, Offer } from './catalog.service';

/** What an alert watches, with the offers of the stores that sell it. */
export interface AlertProduct {
  name: string | null;
  imageUrl: string | null;
  offers: Offer[];
}

export function alertTarget(alert: PriceAlert): string {
  return alert.target || `tesco:${alert.productId}`;
}

export function alertStores(alert: PriceAlert): string[] {
  return alert.stores?.length ? alert.stores : ['tesco'];
}

/** Router link for the watched product. */
export function alertLink(alert: PriceAlert): string[] {
  const target = alertTarget(alert);
  if (target.startsWith('g:')) return ['/p', target];
  if (target.startsWith('tesco:')) return ['/products', target.slice('tesco:'.length)];
  return ['/o', target];
}

/** The watched stores' priced offers, cheapest first. */
export function watchedOffers(alert: PriceAlert, product: AlertProduct | undefined): Offer[] {
  if (!product) return [];
  const stores = alertStores(alert);
  return product.offers
    .filter((o) => stores.includes(o.store) && o.effective_price !== null)
    .sort((a, b) => (a.effective_price ?? 0) - (b.effective_price ?? 0));
}

@Injectable({ providedIn: 'root' })
export class AlertProductsService {
  private catalog = inject(CatalogService);

  /** Resolve every distinct alert target; targets that cannot be loaded are left out. */
  resolve(alerts: PriceAlert[]): Observable<Map<string, AlertProduct>> {
    const targets = [...new Set(alerts.map(alertTarget))];
    if (!targets.length) return of(new Map());
    return forkJoin(targets.map((t) => this.load(t))).pipe(
      map((products) => {
        const result = new Map<string, AlertProduct>();
        products.forEach((p, i) => { if (p) result.set(targets[i], p); });
        return result;
      }),
    );
  }

  private load(target: string): Observable<AlertProduct | null> {
    const request: Observable<AlertProduct> = target.startsWith('g:')
      ? this.catalog.group(target, '').pipe(map((row) => ({ name: row.name, imageUrl: row.image_url, offers: row.offers })))
      : this.catalog.offer(target).pipe(map((offer) => ({ name: offer.name, imageUrl: offer.image_url, offers: [offer] })));
    return request.pipe(catchError(() => of(null)));
  }
}
