import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router } from '@angular/router';
import { of, throwError } from 'rxjs';

import { Search } from './search';
import { AuthService } from '../services/auth.service';
import { CatalogService, RecommendedRows } from '../services/catalog.service';
import { StoresService } from '../services/stores.service';
import { CategoriesService } from '../services/categories.service';

const COLD_START: RecommendedRows = {
  type: 'cold_start',
  personalized_count: 0,
  stores: ['tesco', 'auchan'],
  results: [{
    group_id: 'g:1', gtin: '1', name: 'Deal', brand: null, image_url: null,
    best_price: 100, cheapest_stores: ['tesco'], store_count: 1, offers: [],
  }],
};

describe('Search recommendations', () => {
  it('keeps cold-start results when personalized recommendations fail', () => {
    const recommended = vi.fn((_stores: string, personalized: boolean) =>
      personalized ? throwError(() => new Error('token unavailable')) : of(COLD_START));

    TestBed.configureTestingModule({
      providers: [
        { provide: CatalogService, useValue: { recommended } },
        { provide: StoresService, useValue: { load: () => of([]), storesParam: () => '' } },
        { provide: CategoriesService, useValue: { load: () => of([]), categoryParam: () => '' } },
        { provide: AuthService, useValue: { checkSession: () => of({}), userId: () => 'user-1' } },
        { provide: Router, useValue: { navigate: vi.fn() } },
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { queryParamMap: { get: () => null } } },
        },
      ],
    });

    const component = TestBed.runInInjectionContext(() => new Search());
    component.ngOnInit();

    expect(recommended).toHaveBeenNthCalledWith(1, '', false);
    expect(recommended).toHaveBeenNthCalledWith(2, '', true);
    expect(component.recommendations()).toEqual(COLD_START.results);
    expect(component.recommendationType()).toBe('cold_start');
    expect(component.loadingRecs()).toBe(false);
  });
});
