import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { CatalogService, Offer, PriceSet, ProductRow, bestPriceKind, rowLink } from './catalog.service';
import { alignSeries, bestOfDay } from '../compare/compare-page';
import { offerLink } from './platform-stats.service';

function prices(values: Partial<PriceSet>): PriceSet {
  return { regular: null, promo: null, loyalty: null, unit_price: null, unit: null, ...values };
}

function offer(store: string, id: string, values: Partial<Offer> = {}): Offer {
  return {
    store, ref: `${store}:${id}`, store_product_id: id, gtin: null, group_id: null, is_weighed: false,
    name: 'Tej', brand: null, image_url: null, category_path: [], pack_size: null, pack_unit: null,
    availability: 'available', prices: prices({ regular: 100 }), effective_price: 100, discount_ratio: 0,
    price_date: '2026-09-17', flags: [], url: null, ...values,
  };
}

function row(offers: Offer[], groupId: string | null = null): ProductRow {
  return {
    group_id: groupId, gtin: null, name: 'Tej', brand: null, image_url: null, best_price: 100,
    cheapest_stores: [], store_count: offers.length, offers,
  };
}

describe('catalogue helpers', () => {
  it('links linked products to the comparison page and single offers to their store page', () => {
    expect(rowLink(row([offer('tesco', '1'), offer('auchan', '2')], 'g:54026193'))).toEqual(['/p', 'g:54026193']);
    expect(rowLink(row([offer('tesco', '121262922')]))).toEqual(['/products', '121262922']);
    expect(rowLink(row([offer('auchan', '678170')]))).toEqual(['/o', 'auchan:678170']);
  });

  it('names the lowest of regular, promo and card price', () => {
    expect(bestPriceKind(prices({ regular: 1099, loyalty: 899 }))).toBe('loyalty');
    expect(bestPriceKind(prices({ regular: 969, promo: 629, loyalty: 700 }))).toBe('promo');
    expect(bestPriceKind(prices({ regular: 500 }))).toBe('regular');
    expect(bestPriceKind(prices({}))).toBeNull();
  });

  it('links statistics entries by offer reference', () => {
    expect(offerLink('tesco:121262922')).toEqual(['/products', '121262922']);
    expect(offerLink('auchan:678170')).toEqual(['/o', 'auchan:678170']);
  });

  it('aligns store histories on shared dates using each day\'s best price', () => {
    const history = (date: string, regular: number, promo: number | null = null) =>
      ({ date, availability: null, ...prices({ regular, promo }) });
    expect(bestOfDay(history('2026-09-17', 400, 300))).toBe(300);

    const aligned = alignSeries([
      { store: 'tesco', ref: 'tesco:1', history: [history('2026-06-01', 420), history('2026-09-16', 410), history('2026-09-17', 400, 350)] },
      { store: 'auchan', ref: 'auchan:2', history: [history('2026-09-17', 390)] },
    ], 30, new Date('2026-09-17T12:00:00Z'));

    expect(aligned.labels).toEqual(['2026-09-16', '2026-09-17']);
    expect(aligned.values['tesco:1']).toEqual([410, 350]);
    expect(aligned.values['auchan:2']).toEqual([null, 390]);
    expect(alignSeries([], 0).labels).toEqual([]);
  });
});

describe('CatalogService', () => {
  it('sends the store selection and paging to the row endpoints', () => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    const service = TestBed.inject(CatalogService);
    const http = TestBed.inject(HttpTestingController);

    service.search('tej', 'auchan', 50, 50).subscribe();
    const search = http.expectOne((req) => req.url === '/api/tesco/search');
    expect(search.request.params.get('q')).toBe('tej');
    expect(search.request.params.get('stores')).toBe('auchan');
    expect(search.request.params.get('skip')).toBe('50');

    service.browse('', 0, 50, 'price', 'desc').subscribe();
    const browse = http.expectOne((req) => req.url === '/api/tesco/browse');
    expect(browse.request.params.has('stores')).toBe(false);
    expect(browse.request.params.get('sort_by')).toBe('price');
    expect(browse.request.params.get('sort_dir')).toBe('desc');

    service.group('g:54026193', '').subscribe();
    http.expectOne('/api/tesco/groups/g%3A54026193');
    service.offerHistory('auchan:678170').subscribe();
    http.expectOne('/api/tesco/offers/auchan%3A678170/history');
    http.verify();
  });
});
