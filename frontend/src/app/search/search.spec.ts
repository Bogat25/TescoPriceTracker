import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router } from '@angular/router';
import { Observable, Subject, of, throwError } from 'rxjs';

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

const DRINKS = 'italok/uditok';

function rows(name: string, type: RecommendedRows['type'] = 'cold_start'): RecommendedRows {
  return { ...COLD_START, type, results: [{ ...COLD_START.results[0], name }] };
}

function setUp(
  recommended: (stores: string, personalized: boolean, category?: string) => Observable<RecommendedRows>,
  category: () => string = () => '',
  userId: () => string | null = () => 'user-1',
): Search {
  TestBed.configureTestingModule({
    providers: [
      { provide: CatalogService, useValue: { recommended } },
      { provide: StoresService, useValue: { load: () => of([]), storesParam: () => '' } },
      { provide: CategoriesService, useValue: { load: () => of([]), categoryParam: category, name: (id: string) => id } },
      { provide: AuthService, useValue: { checkSession: () => of({}), userId } },
      { provide: Router, useValue: { navigate: vi.fn() } },
      {
        provide: ActivatedRoute,
        useValue: { snapshot: { queryParamMap: { get: () => null } } },
      },
    ],
  });
  return TestBed.runInInjectionContext(() => new Search());
}

describe('Search recommendations', () => {
  it('falls back to the deals when personalized recommendations fail', () => {
    const recommended = vi.fn((_stores: string, personalized: boolean) =>
      personalized ? throwError(() => new Error('token unavailable')) : of(COLD_START));

    const component = setUp(recommended);
    component.ngOnInit();

    expect(recommended).toHaveBeenNthCalledWith(1, '', true, '');
    expect(recommended).toHaveBeenNthCalledWith(2, '', false, '');
    expect(component.recommendations()).toEqual(COLD_START.results);
    expect(component.recommendationType()).toBe('cold_start');
    expect(component.recsCategory()).toBe('');
    expect(component.loadingRecs()).toBe(false);
  });

  it('a signed-in user never sees the deals flash up before their picks', () => {
    const picks = new Subject<RecommendedRows>();
    const recommended = vi.fn((_stores: string, personalized: boolean) =>
      personalized ? picks : of(rows('Generic deal')));

    const component = setUp(recommended, () => DRINKS);
    component.ngOnInit();

    // While the picks are on their way: a spinner, not the generic deals.
    expect(component.loadingRecs()).toBe(true);
    expect(component.recommendations()).toEqual([]);

    picks.next(rows('Picked cola', 'personalized'));

    expect(recommended).toHaveBeenCalledTimes(1);
    expect(recommended).toHaveBeenCalledWith('', true, DRINKS);
    expect(component.recommendations()[0].name).toBe('Picked cola');
    expect(component.recsCategory()).toBe(DRINKS);
    expect(component.loadingRecs()).toBe(false);
  });

  it('a signed-out visitor gets the category deals only', () => {
    const recommended = vi.fn(() => of(rows('Cheap cola')));

    const component = setUp(recommended, () => DRINKS, () => null);
    component.ngOnInit();

    expect(recommended).toHaveBeenCalledTimes(1);
    expect(recommended).toHaveBeenCalledWith('', false, DRINKS);
    expect(component.recommendations()[0].name).toBe('Cheap cola');
  });

  it('a slower answer for the previous category never replaces the new one', () => {
    let category = '';
    const stale = new Subject<RecommendedRows>();
    const recommended = vi.fn((_stores: string, _personalized: boolean, asked?: string) =>
      asked === DRINKS ? of(rows('Cola')) : stale);

    const component = setUp(recommended, () => category, () => null);
    component.ngOnInit();                    // every category: still on its way

    category = DRINKS;
    component.onCategoryChanged();           // the user picks drinks meanwhile
    stale.next(rows('Everything'));          // the old answer arrives late

    expect(component.recommendations()[0].name).toBe('Cola');
    expect(component.recsCategory()).toBe(DRINKS);
  });
});
