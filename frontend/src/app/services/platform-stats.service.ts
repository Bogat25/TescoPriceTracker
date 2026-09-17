import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, map, shareReplay, switchMap } from 'rxjs';
import { AppConfigService } from './app-config.service';
import { StoresService } from './stores.service';

export interface PriceIndexPoint {
  date: string;
  index: number;
}

export interface ProductVolume {
  total: number;
  active_today: number;
  historical_only: number;
}

export interface PriceTier {
  tier: string;
  count: number;
}

export interface CategoryDiff {
  avg_normal: number | null;
  avg_discount: number | null;
  avg_clubcard: number | null;
  discount_vs_normal_pct: number | null;
  clubcard_vs_normal_pct: number | null;
  products_with_discount: number;
  products_with_clubcard: number;
}

export interface TopDiscountGroup {
  pct_off: number;
  products: {
    tpnc: string;
    name: string;
    normal_price: number;
    discount_price: number;
    promo_desc?: string;
  }[];
}

export interface BestShoppingDay {
  date: string | null;
  total_savings: number | null;
}

export interface DiscountByWeekday {
  weekday: string;
  avg_pct_off: number;
  total_events: number;
}

export interface VolatilityTier {
  tier: string;
  avg_volatility: number;
  product_count: number;
}

export interface GlobalAvg {
  avg_price: number | null;
  product_count: number;
}

export interface Inflation30d {
  /** Change over the products priced on both days. */
  pct_change: number | null;
  paired_products?: number;
  avg_today: number | null;
  avg_30d_ago: number | null;
  date_today: string;
  date_30d_ago: string;
}

export interface PriceDrop {
  /** Offer reference (``store:id``); named tpnc for the existing templates. */
  tpnc: string;
  name: string;
  yesterday_price: number;
  today_price: number;
  drop_amount: number;
  drop_pct: number;
}

/** Raw per-store response of GET /insights. */
interface StoreInsights {
  price_index: PriceIndexPoint[];
  product_counts: ProductVolume;
  price_tiers: PriceTier[];
  price_channels: {
    avg_regular: number | null; avg_promo: number | null; avg_loyalty: number | null;
    promo_vs_regular_pct: number | null; loyalty_vs_regular_pct: number | null;
    products_with_promo: number; products_with_loyalty: number;
  };
  best_shopping_day: BestShoppingDay;
  discount_by_weekday: DiscountByWeekday[];
  volatility: VolatilityTier[];
  global_avg: GlobalAvg;
  inflation_30d: Inflation30d;
}

export interface StoreComparison {
  stores: string[];
  date: string;
  linked_products: number;
  cheapest_by_regular_price: Record<string, number>;
  cheapest_by_best_price: Record<string, number>;
  ties: { regular: number; best: number };
  price_index_vs_cheapest: Record<string, number | null>;
  categories: { category: string; products: number; price_index_vs_cheapest: Record<string, number> }[];
  basket: { date: string; items: number; totals: Record<string, number> }[];
  category_source: string | null;
  note: string;
}

/** Link for an offer reference: the rich Tesco page, otherwise the store-neutral offer page. */
export function offerLink(ref: string): string[] {
  const [store, id] = ref.split(/:(.*)/s);
  return store === 'tesco' ? ['/products', id] : ['/o', ref];
}

/**
 * Store-neutral statistics from GET /insights, mapped to the shapes the
 * statistics and home pages were built for. Every method takes a store ID and
 * defaults to the first selected store.
 */
@Injectable({ providedIn: 'root' })
export class PlatformStatsService {
  private http = inject(HttpClient);
  private config = inject(AppConfigService);
  private stores = inject(StoresService);
  private get base() { return this.config.apiBaseUrl + '/insights'; }
  private cache = new Map<string, Observable<StoreInsights>>();

  private storeId(store?: string): Observable<string> {
    return this.stores.load().pipe(map(() => store ?? this.stores.selected()[0] ?? 'tesco'));
  }

  private insights(store?: string): Observable<StoreInsights> {
    return this.storeId(store).pipe(
      switchMap((id) => {
        if (!this.cache.has(id)) {
          this.cache.set(id, this.http.get<{ by_store: Record<string, StoreInsights> }>(this.base, { params: { stores: id } }).pipe(
            map((res) => res.by_store[id]),
            shareReplay(1),
          ));
        }
        return this.cache.get(id)!;
      }),
    );
  }

  priceIndex(store?: string): Observable<PriceIndexPoint[]> {
    return this.insights(store).pipe(map((d) => d.price_index));
  }

  productVolume(store?: string): Observable<ProductVolume> {
    return this.insights(store).pipe(map((d) => d.product_counts));
  }

  priceTiers(store?: string): Observable<PriceTier[]> {
    return this.insights(store).pipe(map((d) => d.price_tiers));
  }

  categoryDiff(store?: string): Observable<CategoryDiff> {
    return this.insights(store).pipe(map(({ price_channels: c }) => ({
      avg_normal: c.avg_regular,
      avg_discount: c.avg_promo,
      avg_clubcard: c.avg_loyalty,
      discount_vs_normal_pct: c.promo_vs_regular_pct,
      clubcard_vs_normal_pct: c.loyalty_vs_regular_pct,
      products_with_discount: c.products_with_promo,
      products_with_clubcard: c.products_with_loyalty,
    })));
  }

  topDiscounts(store?: string): Observable<TopDiscountGroup[]> {
    return this.storeId(store).pipe(
      switchMap((id) => this.http.get<{ results: { ref: string; name: string; regular: number; promo: number; pct_off: number }[] }>(
        `${this.base}/top-discounts`, { params: { stores: id, limit: 500 } },
      )),
      map((res) => {
        const groups = new Map<number, TopDiscountGroup>();
        for (const item of res.results) {
          const group = groups.get(item.pct_off) ?? { pct_off: item.pct_off, products: [] };
          group.products.push({ tpnc: item.ref, name: item.name, normal_price: item.regular, discount_price: item.promo });
          groups.set(item.pct_off, group);
        }
        return [...groups.values()].sort((a, b) => b.pct_off - a.pct_off);
      }),
    );
  }

  bestShoppingDay(store?: string): Observable<BestShoppingDay> {
    return this.insights(store).pipe(map((d) => d.best_shopping_day));
  }

  discountByWeekday(store?: string): Observable<DiscountByWeekday[]> {
    return this.insights(store).pipe(map((d) => d.discount_by_weekday));
  }

  volatility(store?: string): Observable<VolatilityTier[]> {
    return this.insights(store).pipe(map((d) => d.volatility));
  }

  globalAvg(store?: string): Observable<GlobalAvg> {
    return this.insights(store).pipe(map((d) => d.global_avg));
  }

  inflation30d(store?: string): Observable<Inflation30d> {
    return this.insights(store).pipe(map((d) => d.inflation_30d));
  }

  priceDropsToday(store?: string): Observable<PriceDrop[]> {
    return this.storeId(store).pipe(
      switchMap((id) => this.http.get<{ results: { ref: string; name: string; yesterday: number; today: number; drop_amount: number; drop_pct: number }[] }>(
        `${this.base}/price-drops`, { params: { stores: id, limit: 500 } },
      )),
      map((res) => res.results.map((d) => ({
        tpnc: d.ref, name: d.name, yesterday_price: d.yesterday, today_price: d.today,
        drop_amount: d.drop_amount, drop_pct: d.drop_pct,
      }))),
    );
  }

  /** Stores compared on the products they all sell ('' = every enabled store). */
  comparison(stores: string): Observable<StoreComparison> {
    return this.http.get<StoreComparison>(`${this.base}/compare`, { params: stores ? { stores } : {} });
  }
}
