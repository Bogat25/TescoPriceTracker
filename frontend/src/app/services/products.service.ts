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
  discount_price?: number;
  discount_desc?: string;
  clubcard_price?: number;
  clubcard_desc?: string;
  unit_price?: number;
  unit_measure?: string;
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
  discountPrice?: number;
  discountDesc?: string;
  clubcardPrice?: number;
  clubcardDesc?: string;
  unitPrice?: number;
  unitMeasure?: string;
  unit?: string;
  packSize?: string;
  brand?: string;
  category?: string;
  superDepartment?: string;
  department?: string;
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

export interface RecommendationResponse {
  recommendations: ProductSummary[];
  type: 'cold_start' | 'personalized';
  count: number;
  categories_used?: string[];
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
    discountPrice: p.discount_price != null ? p.discount_price : undefined,
    discountDesc: p.discount_desc,
    clubcardPrice: p.clubcard_price != null ? p.clubcard_price : undefined,
    clubcardDesc: p.clubcard_desc,
    unitPrice: p.unit_price != null ? p.unit_price : undefined,
    unitMeasure: p.unit_measure || p.unit_of_measure,
    unit: p.unit_of_measure,
    packSize,
    brand: p.brand_name,
    category: categoryParts,
    superDepartment: p.super_department_name,
    department: p.department_name,
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
  browse(skip = 0, limit = 100, sortBy?: string, sortDir?: string): Observable<{ results: ProductSummary[]; total: number; skip: number; limit: number }> {
    const params: Record<string, string | number> = { skip, limit };
    if (sortBy)  params['sort_by']  = sortBy;
    if (sortDir) params['sort_dir'] = sortDir;
    return this.http.get<any[]>(`${this.base}/browse`, { params }).pipe(
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

  /** Full-text search; upstream returns {results, total, skip, limit}. */
  searchRaw(query: string, skip = 0, limit = 50): Observable<{ results: ProductResponse[]; total: number; skip: number; limit: number }> {
    const params = new HttpParams().set('q', query).set('skip', skip).set('limit', limit);
    return this.http.get<{ results: ProductResponse[]; total: number; skip: number; limit: number }>(`${this.base}/search`, { params });
  }

  /** Paged search returning ProductSummary list plus total count. */
  searchPaged(query: string, skip = 0, limit = 50): Observable<{ results: ProductSummary[]; total: number }> {
    return this.searchRaw(query, skip, limit).pipe(
      map((r) => ({ results: (r.results ?? []).map(toSummary), total: r.total ?? 0 })),
    );
  }

  /** Backwards-compat wrapper — returns first page. */
  search(query: string): Observable<{ results: ProductSummary[] }> {
    return this.searchPaged(query, 0, 50);
  }

  /** Slim search — returns only card-display fields (no price_history). */
  searchSlim(query: string, skip = 0, limit = 50): Observable<{ results: ProductSummary[]; total: number; skip: number; limit: number }> {
    const params = new HttpParams().set('q', query).set('skip', skip).set('limit', limit);
    return this.http.get<{ results: ProductResponse[]; total: number; skip: number; limit: number }>(`${this.base}/search/slim`, { params }).pipe(
      map(r => ({ results: (r.results ?? []).map(toSummary), total: r.total ?? 0, skip: r.skip ?? skip, limit: r.limit ?? limit })),
    );
  }

  /** Category-aware catalogue search — respects active super_department / department filters. */
  catalogueSearch(
    query: string,
    superDepartment?: string,
    department?: string,
    skip = 0,
    limit = 64,
  ): Observable<{ results: ProductSummary[]; total: number; skip: number; limit: number }> {
    let params = new HttpParams().set('q', query).set('skip', skip).set('limit', limit);
    if (superDepartment) params = params.set('super_department', superDepartment);
    if (department)      params = params.set('department', department);
    return this.http.get<{ results: ProductResponse[]; total: number; skip: number; limit: number }>(
      `${this.base}/catalogue/search`, { params },
    ).pipe(
      map(r => ({ results: (r.results ?? []).map(toSummary), total: r.total ?? 0, skip: r.skip ?? skip, limit: r.limit ?? limit })),
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

  /** Fetch AI-powered product recommendations.
   *  If userId is provided, returns personalized results based on tracked items.
   *  Otherwise returns globally discounted products (cold start). */
  getRecommendations(userId?: string | null, limit = 20): Observable<RecommendationResponse> {
    let params = new HttpParams().set('limit', limit);
    if (userId) {
      params = params.set('userId', userId);
    }
    return this.http.get<RecommendationResponse>(
      `${this.config.tescoApiBaseUrl}/recommendations`,
      { params },
    ).pipe(
      map(res => ({
        ...res,
        recommendations: (res.recommendations ?? []).map(p => toSummary(p as any)),
      })),
    );
  }
}
