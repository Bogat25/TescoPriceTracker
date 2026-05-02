import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { AppConfigService } from './app-config.service';

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
  pct_change: number | null;
  avg_today: number | null;
  avg_30d_ago: number | null;
  date_today: string;
  date_30d_ago: string;
}

export interface PriceDrop {
  tpnc: string;
  name: string;
  yesterday_price: number;
  today_price: number;
  drop_amount: number;
  drop_pct: number;
}

@Injectable({ providedIn: 'root' })
export class PlatformStatsService {
  private http = inject(HttpClient);
  private config = inject(AppConfigService);
  private readonly base = '/api/v1/stats';

  priceIndex(): Observable<PriceIndexPoint[]> {
    return this.http.get<PriceIndexPoint[]>(`${this.base}/price-index`);
  }

  productVolume(): Observable<ProductVolume> {
    return this.http.get<ProductVolume>(`${this.base}/product-volume`);
  }

  priceTiers(): Observable<PriceTier[]> {
    return this.http.get<PriceTier[]>(`${this.base}/price-tiers`);
  }

  categoryDiff(): Observable<CategoryDiff> {
    return this.http.get<CategoryDiff>(`${this.base}/category-diff`);
  }

  topDiscounts(date?: string): Observable<TopDiscountGroup[]> {
    const url = date ? `${this.base}/top-discounts?date=${date}` : `${this.base}/top-discounts`;
    return this.http.get<TopDiscountGroup[]>(url);
  }

  bestShoppingDay(): Observable<BestShoppingDay> {
    return this.http.get<BestShoppingDay>(`${this.base}/best-shopping-day`);
  }

  discountByWeekday(): Observable<DiscountByWeekday[]> {
    return this.http.get<DiscountByWeekday[]>(`${this.base}/discount-by-weekday`);
  }

  volatility(): Observable<VolatilityTier[]> {
    return this.http.get<VolatilityTier[]>(`${this.base}/volatility`);
  }

  globalAvg(): Observable<GlobalAvg> {
    return this.http.get<GlobalAvg>(`${this.base}/global-avg`);
  }

  inflation30d(): Observable<Inflation30d> {
    return this.http.get<Inflation30d>(`${this.base}/inflation/30d`);
  }

  priceDropsToday(): Observable<PriceDrop[]> {
    return this.http.get<PriceDrop[]>(`${this.base}/price-drops/today`);
  }
}
