import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { Subject, of } from 'rxjs';
import { debounceTime, distinctUntilChanged, catchError } from 'rxjs/operators';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  CatalogService, Offer, ProductRow, RowPage, SortBy, SortDir, bestPriceKind, rowLink,
} from '../services/catalog.service';
import { StoresService } from '../services/stores.service';
import { TranslationService } from '../services/translation.service';
import { TranslatePipe } from '../shared/translate.pipe';
import { SecLabel } from '../shared/sec-label/sec-label';
import { StoreSelector } from '../shared/store-selector/store-selector';
import { storeAccent } from '../shared/store-accent';

const PAGE_SIZE = 50;
const MAX_WINDOW = 1000; // the API serves at most the first 1000 results

@Component({
  selector: 'app-products-list',
  imports: [CommonModule, RouterLink, FormsModule, SecLabel, StoreSelector, TranslatePipe],
  templateUrl: './products-list.html',
  styleUrl: './products-list.scss',
})
export class ProductsList implements OnInit {
  private catalog = inject(CatalogService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);
  readonly stores = inject(StoresService);
  readonly tl = inject(TranslationService);

  readonly rows = signal<ProductRow[]>([]);
  readonly loading = signal(true);
  readonly loadingMore = signal(false);
  readonly error = signal('');
  readonly query = signal('');
  readonly sortField = signal<SortBy>('name');
  readonly sortDir = signal<SortDir>('asc');
  readonly total = signal(0);
  private skip = 0;
  private lastPageSize = 0;
  private request = 0;
  private query$ = new Subject<string>();

  readonly searching = computed(() => this.query().trim().length > 0);
  readonly hasMore = computed(() =>
    this.lastPageSize === PAGE_SIZE && this.skip < Math.min(this.total(), MAX_WINDOW) && this.rows().length > 0,
  );

  constructor() {
    this.query$
      .pipe(debounceTime(300), distinctUntilChanged(), takeUntilDestroyed())
      .subscribe(() => this.reload());
  }

  ngOnInit(): void {
    const params = this.route.snapshot.queryParamMap;
    const sort = params.get('sort');
    const dir = params.get('dir');
    if (sort === 'name' || sort === 'price' || sort === 'discount') this.sortField.set(sort);
    if (dir === 'asc' || dir === 'desc') this.sortDir.set(dir);
    this.query.set(params.get('q') ?? '');
    this.stores.load().subscribe(() => this.reload());
  }

  reload(): void {
    this.skip = 0;
    this.rows.set([]);
    this.loading.set(true);
    this.fetchPage();
  }

  loadMore(): void {
    if (this.loadingMore() || !this.hasMore()) return;
    this.loadingMore.set(true);
    this.fetchPage();
  }

  private fetchPage(): void {
    const request = ++this.request;
    const q = this.query().trim();
    const stores = this.stores.storesParam();
    const page$ = q
      ? this.catalog.search(q, stores, this.skip, PAGE_SIZE)
      : this.catalog.browse(stores, this.skip, PAGE_SIZE, this.sortField(), this.sortDir());
    page$.pipe(catchError(() => of(null as RowPage | null))).subscribe((page) => {
      if (request !== this.request) return; // a newer query or sort replaced this one
      this.loading.set(false);
      this.loadingMore.set(false);
      if (!page) {
        this.error.set(this.tl.t('catalogue.error'));
        return;
      }
      this.error.set('');
      this.rows.update((prev) => [...prev, ...page.results]);
      this.total.set(page.total);
      this.skip += PAGE_SIZE;
      this.lastPageSize = page.results.length;
    });
  }

  setSort(field: SortBy): void {
    if (this.sortField() === field) {
      this.sortDir.update((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      this.sortField.set(field);
      this.sortDir.set(field === 'discount' ? 'desc' : 'asc');
    }
    this.pushUrlParams();
    if (!this.searching()) this.reload();
  }

  onQueryChange(value: string): void {
    this.query.set(value);
    this.pushUrlParams();
    this.query$.next(value);
  }

  sortIcon(field: SortBy): string {
    if (this.sortField() !== field) return '⇅';
    return this.sortDir() === 'asc' ? '↑' : '↓';
  }

  link(row: ProductRow): string[] {
    return rowLink(row);
  }

  kind(offer: Offer): string {
    return bestPriceKind(offer.prices) ?? 'regular';
  }

  accent(storeId: string): string {
    return storeAccent(storeId);
  }

  /** Largest saving of any offer in the row, as a whole percentage. */
  bestDiscount(row: ProductRow): number | null {
    const ratio = Math.max(0, ...row.offers.map((o) => o.discount_ratio || 0));
    return ratio > 0 ? Math.round(ratio * 100) : null;
  }

  isCheapest(row: ProductRow, offer: Offer): boolean {
    return row.offers.length > 1 && offer.effective_price !== null && offer.effective_price === row.best_price;
  }

  private pushUrlParams(): void {
    const queryParams: Record<string, string> = {};
    if (this.query().trim()) queryParams['q'] = this.query().trim();
    if (this.sortField() !== 'name') queryParams['sort'] = this.sortField();
    if (this.sortDir() !== 'asc') queryParams['dir'] = this.sortDir();
    this.router.navigate([], { queryParams, replaceUrl: true });
  }
}
