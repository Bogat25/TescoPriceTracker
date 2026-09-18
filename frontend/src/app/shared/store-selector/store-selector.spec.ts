import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { StoreSelector } from './store-selector';
import { StoresService } from '../../services/stores.service';

const STORES = {
  stores: [
    { id: 'tesco', name: 'Tesco', order: 10, website: 'https://bevasarlas.tesco.hu' },
    { id: 'auchan', name: 'Auchan', order: 20, website: 'https://auchan.hu' },
  ],
};

function setup(stores = STORES) {
  localStorage.clear();
  TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
  const fixture = TestBed.createComponent(StoreSelector);
  const http = TestBed.inject(HttpTestingController);
  fixture.detectChanges();                        // ngOnInit asks for the store list
  http.expectOne('/api/prices/stores').flush(stores);
  fixture.detectChanges();
  return { fixture, component: fixture.componentInstance, http };
}

function chips(fixture: { nativeElement: HTMLElement }): HTMLButtonElement[] {
  return Array.from(fixture.nativeElement.querySelectorAll<HTMLButtonElement>('.ss-chip'));
}

describe('StoreSelector', () => {
  afterEach(() => localStorage.clear());

  it('shows one chip per store, in registry order, all selected', () => {
    const { fixture } = setup();
    const buttons = chips(fixture);
    expect(buttons.map((b) => b.textContent?.trim())).toEqual(['Tesco', 'Auchan']);
    expect(buttons.map((b) => b.getAttribute('aria-pressed'))).toEqual(['true', 'true']);
  });

  it('stays out of the way when there is only one store', () => {
    const { fixture } = setup({ stores: [STORES.stores[0]] });
    expect(chips(fixture)).toEqual([]);
  });

  it('deselects a store on click and tells the page to reload', () => {
    const { fixture, component } = setup();
    const changed = vi.fn();
    component.changed.subscribe(changed);

    chips(fixture)[0].click();
    fixture.detectChanges();

    expect(component.stores.selected()).toEqual(['auchan']);
    expect(component.stores.storesParam()).toBe('auchan');
    expect(chips(fixture)[0].getAttribute('aria-pressed')).toBe('false');
    expect(changed).toHaveBeenCalledTimes(1);
  });

  it('refuses to switch off the last store, and says nothing changed', () => {
    const { fixture, component } = setup();
    const changed = vi.fn();
    component.changed.subscribe(changed);

    chips(fixture)[0].click();      // only Auchan left
    chips(fixture)[1].click();      // would leave nothing
    fixture.detectChanges();

    expect(component.stores.selected()).toEqual(['auchan']);
    expect(changed).toHaveBeenCalledTimes(1);
  });

  it('remembers the selection for the next visit', () => {
    const { fixture } = setup();
    chips(fixture)[1].click();
    expect(JSON.parse(localStorage.getItem('pt_selected_stores') ?? '[]')).toEqual(['tesco']);
  });

  it('gives each store its own accent colour', () => {
    const { component } = setup();
    expect(component.accent('tesco')).not.toBe(component.accent('auchan'));
  });

  it('survives a store list that cannot be loaded', () => {
    localStorage.clear();
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    const fixture = TestBed.createComponent(StoreSelector);
    fixture.detectChanges();
    TestBed.inject(HttpTestingController).expectOne('/api/prices/stores').error(new ProgressEvent('offline'));
    fixture.detectChanges();

    expect(chips(fixture)).toEqual([]);
    expect(TestBed.inject(StoresService).stores()).toEqual([]);
  });
});
