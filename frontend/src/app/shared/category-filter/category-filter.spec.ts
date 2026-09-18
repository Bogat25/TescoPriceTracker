import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { CategoryFilter } from './category-filter';
import { CategoriesService } from '../../services/categories.service';

const CATEGORIES = [
  { id: 'alapveto-elelmiszerek/tejtermekek', names: ['Alapvető élelmiszerek', 'Tejtermékek'], name: 'Tejtermékek', counts: { tesco: 120, auchan: 60 }, products: 180 },
  { id: 'italok/uditok', names: ['Italok', 'Üdítők'], name: 'Üdítők', counts: { tesco: 80, auchan: 0 }, products: 80 },
];

function setup(categories = CATEGORIES) {
  TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
  const service = TestBed.inject(CategoriesService);
  service.load('').subscribe();
  TestBed.inject(HttpTestingController).expectOne('/api/prices/categories').flush({ categories });
  const fixture = TestBed.createComponent(CategoryFilter);
  fixture.detectChanges();
  return { fixture, component: fixture.componentInstance, service, element: fixture.nativeElement as HTMLElement };
}

describe('CategoryFilter', () => {
  it('offers every category plus an "all" option, with product counts', () => {
    const { element } = setup();
    const options = Array.from(element.querySelectorAll('option')).map((o) => o.textContent?.trim());
    expect(options).toEqual(['All categories', 'Tejtermékek (180)', 'Üdítők (80)']);
  });

  it('hides itself when the mapping has nothing to offer', () => {
    const { element } = setup([]);
    expect(element.querySelector('select')).toBeNull();
  });

  it('applies a choice and tells the page to reload', () => {
    const { component, service, element, fixture } = setup();
    const changed = vi.fn();
    component.changed.subscribe(changed);

    const select = element.querySelector('select')!;
    select.value = CATEGORIES[1].id;
    select.dispatchEvent(new Event('change'));
    fixture.detectChanges();

    expect(service.categoryParam()).toBe(CATEGORIES[1].id);
    expect(changed).toHaveBeenCalledTimes(1);
  });

  it('offers a way back to everything', () => {
    const { component, service, element, fixture } = setup();
    component.choose(CATEGORIES[0].id);
    fixture.detectChanges();

    const clear = element.querySelector<HTMLButtonElement>('.cf-clear')!;
    expect(clear).not.toBeNull();
    clear.click();
    fixture.detectChanges();

    expect(service.categoryParam()).toBe('');
    expect(element.querySelector('.cf-clear')).toBeNull();
  });

  it('says nothing when the same category is chosen again', () => {
    const { component } = setup();
    const changed = vi.fn();
    component.changed.subscribe(changed);

    component.choose(CATEGORIES[0].id);
    component.choose(CATEGORIES[0].id);

    expect(changed).toHaveBeenCalledTimes(1);
  });
});
