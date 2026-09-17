import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { StoresService } from './stores.service';

const STORES = {
  stores: [
    { id: 'auchan', name: 'Auchan', order: 20, website: 'https://auchan.hu' },
    { id: 'tesco', name: 'Tesco', order: 10, website: 'https://bevasarlas.tesco.hu' },
  ],
};

function setup(stored?: string[]) {
  localStorage.clear();
  if (stored) localStorage.setItem('pt_selected_stores', JSON.stringify(stored));
  TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
  const service = TestBed.inject(StoresService);
  const http = TestBed.inject(HttpTestingController);
  service.load().subscribe();
  http.expectOne('/api/tesco/stores').flush(STORES);
  return { service, http };
}

describe('StoresService', () => {
  afterEach(() => localStorage.clear());

  it('orders stores by registry order and selects every store by default', () => {
    const { service } = setup();
    expect(service.stores().map((s) => s.id)).toEqual(['tesco', 'auchan']);
    expect(service.selected()).toEqual(['tesco', 'auchan']);
    expect(service.storesParam()).toBe('');
    expect(service.showSelector()).toBe(true);
  });

  it('narrows the selection, remembers it, and never deselects the last store', () => {
    const { service } = setup();
    service.toggle('tesco');
    expect(service.selected()).toEqual(['auchan']);
    expect(service.storesParam()).toBe('auchan');
    expect(JSON.parse(localStorage.getItem('pt_selected_stores')!)).toEqual(['auchan']);

    service.toggle('auchan');
    expect(service.selected()).toEqual(['auchan']);
  });

  it('ignores remembered stores that are no longer enabled', () => {
    const { service } = setup(['lidl']);
    expect(service.selected()).toEqual(['tesco', 'auchan']);
    expect(service.storesParam()).toBe('');
  });

  it('keeps a remembered selection in registry order', () => {
    const { service } = setup(['auchan']);
    expect(service.storesParam()).toBe('auchan');
    service.toggle('tesco');
    expect(service.selected()).toEqual(['tesco', 'auchan']);
    expect(service.storesParam()).toBe('');
  });

  it('hides the selector when only one store is enabled', () => {
    localStorage.clear();
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    const service = TestBed.inject(StoresService);
    service.load().subscribe();
    TestBed.inject(HttpTestingController).expectOne('/api/tesco/stores').flush({ stores: [STORES.stores[1]] });
    expect(service.showSelector()).toBe(false);
    expect(service.name('tesco')).toBe('Tesco');
    expect(service.name('unknown')).toBe('unknown');
  });

  it('loads the store list once', () => {
    const { service, http } = setup();
    service.load().subscribe();
    http.expectNone('/api/tesco/stores');
  });
});
