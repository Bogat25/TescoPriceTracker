import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable, map } from 'rxjs';
import { AppConfigService } from './app-config.service';

/** Price point from upstream price_history channel. */
export interface PriceEntry {
  price: number;
  unit_price?: number;
  unit_measure?: string;
  start_date: string;
  end_date: string;
  promo_id?: string;
  promo_desc?: string;
  promo_start?: string;
  promo_end?: string;
}

export interface PriceHistoryChannels {
  normal?: PriceEntry[];
  discount?: PriceEntry[];
  clubcard?: PriceEntry[];
}

/** Raw product response from the upstream Tesco API (see swagger.yaml). */
export interface ProductResponse {
  tpnc: string;
  name: string;
  unit_of_measure: string;
  default_image_url?: string;
  pack_size_value?: number;
  pack_size_unit?: string;
  last_scraped_price: string;
  price_history: PriceHistoryChannels;
  brand_name?: string;
  sub_brand?: string;
  super_department_name?: string;
  department_name?: string;
  aisle_name?: string;
  shelf_name?: string;
  short_description?: string;
  marketing?: string;
  product_marketing?: string;
  ingredients?: string[];
  allergens?: string;
  dietary_info?: Record<string, any>;
  storage?: string;
  preparation_and_usage?: string;
  manufacturer?: string;
  origin_information?: any[];
  overall_rating?: number;
  number_of_reviews?: number;
  storageClassification?: string;
}

/** Thin summary used by list views. Mirrors a subset of ProductResponse. */
export interface ProductSummary {
  tpnc: string;
  name?: string;
  imageUrl?: string;
  currentPrice?: number;
  unit?: string;
  packSize?: string;
  brand?: string;
  category?: string;
  rating?: number;
  reviewCount?: number;
}

/** Extra descriptive fields kept for backwards-compat with detail view. */
export interface ProductDetail extends ProductSummary {
  description?: string;
  raw?: ProductResponse;
  [key: string]: unknown;
}

export interface PricePoint {
  timestamp: string;
  price: number;
}

export interface ProductHistory {
  tpnc: string;
  points: PricePoint[];
}

export interface ProductStats {
  tpnc: string;
  min?: number;
  max?: number;
  avg?: number;
  current?: number;
  pointCount?: number;
  [key: string]: unknown;
}

function parsePrice(raw: unknown): number | undefined {
  if (raw === undefined || raw === null) return undefined;
  const n = typeof raw === 'number' ? raw : Number(String(raw).replace(/[^\d.+-]/g, ''));
  return Number.isFinite(n) ? n : undefined;
}

/** Map a raw upstream ProductResponse into the UI-friendly summary shape. */
export function toSummary(p: ProductResponse): ProductSummary {
  const packSize =
    p.pack_size_value !== undefined && p.pack_size_unit
      ? `${p.pack_size_value}${p.pack_size_unit}`
      : undefined;
      
  const categoryParts = [p.super_department_name, p.department_name].filter(Boolean).join(' > ');

  return {
    tpnc: p.tpnc,
    name: p.name,
    imageUrl: p.default_image_url,
    currentPrice: parsePrice(p.last_scraped_price),
    unit: p.unit_of_measure,
    packSize,
    brand: p.brand_name,
    category: categoryParts,
    rating: p.overall_rating,
    reviewCount: p.number_of_reviews
  };
}

@Injectable({ providedIn: 'root' })
export class ProductsService {
  private http = inject(HttpClient);
  private config = inject(AppConfigService);
  private get base() { return this.config.tescoApiBaseUrl + '/products'; }

  list(): Observable<unknown> {
    return this.http.get(this.base);
  }

  /** Paginated catalogue browse — returns summaries without price_history. */
  browse(skip = 0, limit = 100): Observable<{ results: ProductSummary[]; total: number; skip: number; limit: number }> {
    return this.http.get<any[]>(`${this.base}/browse`, { params: { skip, limit } }).pipe(
      map((res: any) => {
        const raw: any[] = Array.isArray(res) ? res : (res?.results ?? []);
        const total: number = res?.total ?? raw.length;
        return {
          results: raw.map(p => toSummary(p as ProductResponse)),
          total,
          skip: res?.skip ?? skip,
          limit: res?.limit ?? limit,
        };
      }),
    );
  }

  /** Full-text search; upstream returns ProductResponse[]. */
  searchRaw(query: string): Observable<ProductResponse[]> {
    const params = new HttpParams().set('q', query);
    return this.http.get<ProductResponse[]>(`${this.base}/search`, { params });
  }

  /** Backwards-compat wrapper used by existing search component. */
  search(query: string): Observable<{ results: ProductSummary[] }> {
    return this.searchRaw(query).pipe(
      map((arr) => ({ results: (Array.isArray(arr) ? arr : []).map(toSummary) })),
    );
  }

  /** Full upstream document — contains price_history for charting. */
  getRaw(tpnc: string): Observable<ProductResponse> {
    return this.http.get<ProductResponse>(`${this.base}/${encodeURIComponent(tpnc)}/detailed`);
  }

  get(tpnc: string): Observable<ProductDetail> {
    return this.getRaw(tpnc).pipe(map((p) => ({
      ...toSummary(p),
      description: p.product_marketing || p.marketing || p.short_description || undefined,
      raw: p
    })));
  }

  history(tpnc: string): Observable<ProductHistory> {
    return this.http.get<ProductHistory>(`${this.base}/${encodeURIComponent(tpnc)}/history`);
  }

  stats(tpnc: string): Observable<ProductStats> {
    return this.http.get<ProductStats>(`${this.base}/${encodeURIComponent(tpnc)}/stats`);
  }
}
