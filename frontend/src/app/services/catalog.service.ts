import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { AppConfigService } from './app-config.service';

/** Prices of one offer; ``loyalty`` is the store card price (Clubcard, Bizalomkártya). */
export interface PriceSet {
  regular: number | null;
  promo: number | null;
  loyalty: number | null;
  unit_price: number | null;
  unit: string | null;
}

/** One product listing in one store (store-neutral API). */
export interface Offer {
  store: string;
  ref: string;
  store_product_id: string;
  gtin: string | null;
  group_id: string | null;
  is_weighed: boolean;
  name: string | null;
  brand: string | null;
  image_url: string | null;
  category_path: string[];
  pack_size: number | null;
  pack_unit: string | null;
  availability: string | null;
  prices: PriceSet;
  effective_price: number | null;
  discount_ratio: number;
  price_date: string | null;
  flags: string[];
  url: string | null;
}

/** A product with every selected store's offer, cheapest first. */
export interface ProductRow {
  group_id: string | null;
  gtin: string | null;
  name: string | null;
  brand: string | null;
  image_url: string | null;
  best_price: number | null;
  cheapest_stores: string[];
  store_count: number;
  offers: Offer[];
}

export interface RowPage {
  results: ProductRow[];
  total: number;
  skip: number;
  limit: number;
  stores: string[];
  /** Which search answered: text is used when vectors are unavailable. */
  mode?: SearchMode;
}

/** ``hybrid`` fuses text and meaning; ``text`` is the plain index (fast, for suggestions). */
export type SearchMode = 'hybrid' | 'semantic' | 'text';

export interface HistoryRow extends PriceSet {
  date: string;
  availability: string | null;
}

export interface GroupHistory {
  group_id: string;
  series: { store: string; ref: string; history: HistoryRow[] }[];
}

export interface RecommendedRows {
  type: 'cold_start' | 'personalized';
  personalized_count: number;
  results: ProductRow[];
  stores: string[];
}

export type SortBy = 'name' | 'price' | 'discount';
export type SortDir = 'asc' | 'desc';

/** Router link for a row: the comparison page for linked products, else the offer page. */
export function rowLink(row: ProductRow): string[] {
  if (row.group_id) return ['/p', row.group_id];
  const offer = row.offers[0];
  if (offer?.store === 'tesco') return ['/products', offer.store_product_id];
  return ['/o', offer?.ref ?? ''];
}

/** Lowest price a shopper can get for an offer, and which price that is. */
export function bestPriceKind(prices: PriceSet): 'loyalty' | 'promo' | 'regular' | null {
  const candidates: [number | null, 'loyalty' | 'promo' | 'regular'][] = [
    [prices.regular, 'regular'],
    [prices.promo, 'promo'],
    [prices.loyalty, 'loyalty'],
  ];
  let best: [number, 'loyalty' | 'promo' | 'regular'] | null = null;
  for (const [value, kind] of candidates) {
    if (value !== null && value !== undefined && (best === null || value < best[0])) best = [value, kind];
  }
  return best ? best[1] : null;
}

@Injectable({ providedIn: 'root' })
export class CatalogService {
  private http = inject(HttpClient);
  private config = inject(AppConfigService);
  private get base() { return this.config.apiBaseUrl; }

  private params(values: Record<string, string | number | undefined>): HttpParams {
    let params = new HttpParams();
    for (const [key, value] of Object.entries(values)) {
      if (value !== undefined && value !== '') params = params.set(key, value);
    }
    return params;
  }

  search(q: string, stores: string, skip = 0, limit = 50, mode: SearchMode = 'hybrid', category = ''): Observable<RowPage> {
    return this.http.get<RowPage>(`${this.base}/search`, {
      params: this.params({ q, stores, skip, limit, mode, category }),
    });
  }

  /** Products closest in meaning to a group (``g:…``) or an offer ref, excluding the product itself. */
  similar(target: string, stores: string, limit = 12): Observable<{ results: ProductRow[] }> {
    const path = target.startsWith('g:') ? 'groups' : 'offers';
    return this.http.get<{ results: ProductRow[] }>(`${this.base}/${path}/${encodeURIComponent(target)}/similar`, {
      params: this.params({ stores, limit }),
    });
  }

  browse(stores: string, skip = 0, limit = 50, sortBy: SortBy = 'name', sortDir: SortDir = 'asc', category = ''): Observable<RowPage> {
    return this.http.get<RowPage>(`${this.base}/browse`, {
      params: this.params({ stores, skip, limit, sort_by: sortBy, sort_dir: sortDir, category }),
    });
  }

  group(groupId: string, stores: string): Observable<ProductRow> {
    return this.http.get<ProductRow>(`${this.base}/groups/${encodeURIComponent(groupId)}`, { params: this.params({ stores }) });
  }

  groupHistory(groupId: string, stores: string): Observable<GroupHistory> {
    return this.http.get<GroupHistory>(`${this.base}/groups/${encodeURIComponent(groupId)}/history`, {
      params: this.params({ stores }),
    });
  }

  /** Picks for the signed-in user (identity from the Bearer token), or today's best deals. */
  recommended(stores: string, personalized: boolean, limit = 48): Observable<RecommendedRows> {
    const path = personalized ? 'personalized' : 'cold';
    return this.http.get<RecommendedRows>(`${this.base}/recommended/${path}`, { params: this.params({ stores, limit }) });
  }

  offer(ref: string): Observable<Offer> {
    return this.http.get<Offer>(`${this.base}/offers/${encodeURIComponent(ref)}`);
  }

  offerHistory(ref: string): Observable<{ ref: string; history: HistoryRow[] }> {
    return this.http.get<{ ref: string; history: HistoryRow[] }>(`${this.base}/offers/${encodeURIComponent(ref)}/history`);
  }
}
