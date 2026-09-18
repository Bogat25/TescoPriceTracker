import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { CategoriesService } from './categories.service';

const DAIRY = {
  id: 'alapveto-elelmiszerek/tejtermekek',
  names: ['Alapvető élelmiszerek', 'Tejtermékek'],
  name: 'Tejtermékek',
  counts: { tesco: 120, auchan: 60 },
  products: 180,
};
const DRINKS = {
  id: 'italok/uditok',
  names: ['Italok', 'Üdítők'],
  name: 'Üdítők',
  counts: { tesco: 80, auchan: 0 },
  products: 80,
};

function setup() {
  TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
  return { service: TestBed.inject(CategoriesService), http: TestBed.inject(HttpTestingController) };
}

describe('CategoriesService', () => {
  it('loads the vocabulary for the selected stores', () => {
    const { service, http } = setup();
    service.load('tesco').subscribe();
    http.expectOne('/api/prices/categories?stores=tesco').flush({ categories: [DAIRY, DRINKS] });

    expect(service.categories().map((c) => c.name)).toEqual(['Tejtermékek', 'Üdítők']);
    expect(service.available()).toBe(true);
    expect(service.loaded()).toBe(true);
    expect(service.categoryParam()).toBe('');
  });

  it('asks for every enabled store when nothing is narrowed', () => {
    const { service, http } = setup();
    service.load('').subscribe();
    http.expectOne('/api/prices/categories').flush({ categories: [] });
    expect(service.available()).toBe(false);
  });

  it('selects a category and offers it as the query parameter', () => {
    const { service, http } = setup();
    service.load('').subscribe();
    http.expectOne('/api/prices/categories').flush({ categories: [DAIRY] });

    service.select(DAIRY.id);
    expect(service.categoryParam()).toBe(DAIRY.id);
    expect(service.name(DAIRY.id)).toBe('Tejtermékek');

    service.clear();
    expect(service.categoryParam()).toBe('');
  });

  it('ignores a category it does not know', () => {
    const { service, http } = setup();
    service.load('').subscribe();
    http.expectOne('/api/prices/categories').flush({ categories: [DAIRY] });

    service.select('nincs/ilyen');
    expect(service.categoryParam()).toBe('');
  });

  it('drops a selection the new store combination no longer offers', () => {
    const { service, http } = setup();
    service.load('').subscribe();
    http.expectOne('/api/prices/categories').flush({ categories: [DAIRY, DRINKS] });
    service.select(DRINKS.id);

    service.load('auchan').subscribe();
    http.expectOne('/api/prices/categories?stores=auchan').flush({ categories: [DAIRY] });

    expect(service.categoryParam()).toBe('');
  });

  it('keeps a selection the new store combination still offers', () => {
    const { service, http } = setup();
    service.load('').subscribe();
    http.expectOne('/api/prices/categories').flush({ categories: [DAIRY, DRINKS] });
    service.select(DAIRY.id);

    service.load('auchan').subscribe();
    http.expectOne('/api/prices/categories?stores=auchan').flush({ categories: [DAIRY] });

    expect(service.categoryParam()).toBe(DAIRY.id);
  });

  it('treats an unreachable mapping as no categories rather than an error', () => {
    const { service, http } = setup();
    let failed = false;
    service.load('').subscribe({ error: () => (failed = true) });
    http.expectOne('/api/prices/categories').error(new ProgressEvent('offline'));

    expect(failed).toBe(false);
    expect(service.categories()).toEqual([]);
    expect(service.available()).toBe(false);
  });
});
