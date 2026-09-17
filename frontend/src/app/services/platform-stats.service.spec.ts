import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { PlatformStatsService } from './platform-stats.service';

const INSIGHTS = {
  price_index: [], product_counts: { total: 3, active_today: 2, historical_only: 1 }, price_tiers: [],
  price_channels: {
    avg_regular: 1000, avg_promo: 800, avg_loyalty: 900, promo_vs_regular_pct: -20, loyalty_vs_regular_pct: -10,
    products_with_promo: 4, products_with_loyalty: 5,
  },
  best_shopping_day: { date: null, total_savings: null }, discount_by_weekday: [], volatility: [],
  global_avg: { avg_price: 1000, product_count: 3 },
  inflation_30d: { pct_change: 0, paired_products: 2, avg_today: 1, avg_30d_ago: 1, date_today: 'x', date_30d_ago: 'y' },
};

describe('PlatformStatsService', () => {
  let service: PlatformStatsService;
  let http: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    service = TestBed.inject(PlatformStatsService);
    http = TestBed.inject(HttpTestingController);
  });

  function flushStores() {
    http.expectOne('/api/tesco/stores').flush({
      stores: [
        { id: 'tesco', name: 'Tesco', order: 10, website: '' },
        { id: 'auchan', name: 'Auchan', order: 20, website: '' },
      ],
    });
  }

  it('maps store channels to the statistics page fields and caches per store', () => {
    let diff: unknown;
    service.categoryDiff('auchan').subscribe((d) => (diff = d));
    flushStores();
    http.expectOne((req) => req.url === '/api/tesco/insights' && req.params.get('stores') === 'auchan')
      .flush({ by_store: { auchan: INSIGHTS } });
    expect(diff).toEqual({
      avg_normal: 1000, avg_discount: 800, avg_clubcard: 900,
      discount_vs_normal_pct: -20, clubcard_vs_normal_pct: -10,
      products_with_discount: 4, products_with_clubcard: 5,
    });

    let volume: unknown;
    service.productVolume('auchan').subscribe((v) => (volume = v));
    http.expectNone('/api/tesco/insights');
    expect(volume).toEqual({ total: 3, active_today: 2, historical_only: 1 });
  });

  it('defaults to the first selected store and groups top discounts by percentage', () => {
    let groups: { pct_off: number; products: { tpnc: string }[] }[] = [];
    service.topDiscounts().subscribe((g) => (groups = g));
    flushStores();
    http.expectOne((req) => req.url === '/api/tesco/insights/top-discounts' && req.params.get('stores') === 'tesco')
      .flush({ results: [
        { ref: 'tesco:1', name: 'A', regular: 100, promo: 50, pct_off: 50 },
        { ref: 'tesco:2', name: 'B', regular: 100, promo: 75, pct_off: 25 },
        { ref: 'tesco:3', name: 'C', regular: 200, promo: 100, pct_off: 50 },
      ] });
    expect(groups.map((g) => g.pct_off)).toEqual([50, 25]);
    expect(groups[0].products.map((p) => p.tpnc)).toEqual(['tesco:1', 'tesco:3']);
  });
});
