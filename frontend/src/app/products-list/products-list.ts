import { Component, OnInit, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { Subject, of } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap, catchError } from 'rxjs/operators';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ProductsService, ProductSummary } from '../services/products.service';
import { TranslationService } from '../services/translation.service';
import { TranslatePipe } from '../shared/translate.pipe';
import { HexIcon }   from '../shared/hex-icon/hex-icon';
import { SecLabel }  from '../shared/sec-label/sec-label';

type SortField = 'name' | 'price' | 'category' | 'rating' | 'discount';
type SortDir   = 'asc' | 'desc';

const PAGE_SIZE = 100;

/** Lowest effective price across normal, discount, clubcard channels. */
function lowestPrice(p: ProductSummary): number | undefined {
  const candidates = [p.currentPrice, p.discountPrice, p.clubcardPrice].filter((v): v is number => v !== undefined);
  return candidates.length ? Math.min(...candidates) : undefined;
}

@Component({
  selector: 'app-products-list',
  imports: [CommonModule, RouterLink, FormsModule, HexIcon, SecLabel, TranslatePipe],
  templateUrl: './products-list.html',
  styleUrl: './products-list.scss',
})
export class ProductsList implements OnInit {
  private productsApi = inject(ProductsService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);
  readonly tl = inject(TranslationService);

  readonly allProducts = signal<ProductSummary[]>([]);
  readonly loading     = signal(true);
  readonly loadingMore = signal(false);
  readonly error       = signal('');
  readonly query       = signal('');
  readonly sortField   = signal<SortField>('name');
  readonly sortDir     = signal<SortDir>('asc');
  readonly total       = signal(0);
  private  skip        = 0;

  /** Backend catalogue search results (used when a query is typed) */
  readonly searchResults    = signal<ProductSummary[]>([]);
  readonly searchTotal      = signal(0);
  readonly backendSearching = signal(false);
  private  searchQuery$     = new Subject<string>();

  /** Active category filters */
  readonly selectedSuper = signal<string | null>(null);
  readonly selectedDept  = signal<string | null>(null);

  readonly hasMore = computed(() => this.allProducts().length < this.total());

  /** True when there is no more data and no active search */
  readonly allLoaded = computed(() => !this.hasMore() && !this.query().trim() && this.total() > 0);

  /** Unique super-departments from all loaded products, sorted. */
  readonly superDepartments = computed(() => {
    const seen = new Set<string>();
    for (const p of this.allProducts()) {
      if (p.superDepartment) seen.add(p.superDepartment);
    }
    return [...seen].sort((a, b) => a.localeCompare(b));
  });

  /** Unique departments within the selected super-department, sorted. */
  readonly departments = computed(() => {
    const superDept = this.selectedSuper();
    if (!superDept) return [];
    const seen = new Set<string>();
    for (const p of this.allProducts()) {
      if (p.superDepartment === superDept && p.department) seen.add(p.department);
    }
    return [...seen].sort((a, b) => a.localeCompare(b));
  });

  readonly filtered = computed(() => {
    const q      = this.query().trim();
    const superD = this.selectedSuper();
    const dept   = this.selectedDept();
    const f      = this.sortField();
    const d      = this.sortDir() === 'asc' ? 1 : -1;

    const sortFn = (a: ProductSummary, b: ProductSummary): number => {
      if (f === 'price')    return d * ((lowestPrice(a) ?? 0) - (lowestPrice(b) ?? 0));
      if (f === 'discount') {
        const dA = a.discountPrice !== undefined && a.currentPrice ? ((a.currentPrice - a.discountPrice) / a.currentPrice) : 0;
        const dB = b.discountPrice !== undefined && b.currentPrice ? ((b.currentPrice - b.discountPrice) / b.currentPrice) : 0;
        return d * (dA - dB);
      }
      if (f === 'rating')   return d * ((a.rating ?? -1) - (b.rating ?? -1));
      if (f === 'category') return d * (a.category ?? '').localeCompare(b.category ?? '');
      return d * (a.name ?? a.tpnc).localeCompare(b.name ?? b.tpnc);
    };

    if (q) {
      return [...this.searchResults()].sort(sortFn);
    }

    let list = this.allProducts();
    if (superD) list = list.filter(p => p.superDepartment === superD);
    if (dept)   list = list.filter(p => p.department === dept);
    return [...list].sort(sortFn);
  });

  /** Expose lowestPrice helper to template */
  lowestPrice = lowestPrice;

  constructor() {
    this.searchQuery$.pipe(
      debounceTime(300),
      distinctUntilChanged(),
      switchMap(q => {
        const term = q.trim();
        if (!term) {
          this.searchResults.set([]);
          this.searchTotal.set(0);
          this.backendSearching.set(false);
          return of(null);
        }
        this.backendSearching.set(true);
        return this.productsApi.catalogueSearch(
          term,
          this.selectedSuper() ?? undefined,
          this.selectedDept() ?? undefined,
        ).pipe(catchError(() => of(null)));
      }),
      takeUntilDestroyed(),
    ).subscribe(res => {
      this.backendSearching.set(false);
      if (res) {
        this.searchResults.set(res.results);
        this.searchTotal.set(res.total);
      }
    });
  }

  ngOnInit(): void {
    // Restore state from URL query params
    const params = this.route.snapshot.queryParamMap;
    const q     = params.get('q') ?? '';
    const sup   = params.get('super') ?? null;
    const dept  = params.get('dept') ?? null;
    const sort  = (params.get('sort') ?? 'name') as SortField;
    const dir   = (params.get('dir') ?? 'asc') as SortDir;

    if (sup)  this.selectedSuper.set(sup);
    if (dept) this.selectedDept.set(dept);
    this.sortField.set(sort);
    this.sortDir.set(dir);

    this.loadPage().then(() => {
      if (q) {
        this.query.set(q);
        this.searchQuery$.next(q);
      }
    });
  }

  private loadPage(): Promise<void> {
    return new Promise((resolve) => {
      this.productsApi.browse(this.skip, PAGE_SIZE).subscribe({
        next: (res) => {
          this.allProducts.update(prev => [...prev, ...res.results]);
          this.total.set(res.total);
          this.skip += res.results.length;
          this.loading.set(false);
          this.loadingMore.set(false);
          resolve();
        },
        error: () => {
          this.error.set('Could not load products.');
          this.loading.set(false);
          this.loadingMore.set(false);
          resolve();
        },
      });
    });
  }

  loadMore(): void {
    if (this.loadingMore() || !this.hasMore()) return;
    this.loadingMore.set(true);
    this.loadPage();
  }

  setSort(field: SortField): void {
    if (this.sortField() === field) {
      this.sortDir.update(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      this.sortField.set(field);
      this.sortDir.set(field === 'discount' ? 'desc' : 'asc');
    }
    this._pushUrlParams();
  }

  selectSuper(s: string | null): void {
    this.selectedSuper.set(s);
    this.selectedDept.set(null);
    if (this.query().trim()) this.searchQuery$.next(this.query());
    this._pushUrlParams();
  }

  selectDept(d: string | null): void {
    this.selectedDept.set(d);
    if (this.query().trim()) this.searchQuery$.next(this.query());
    this._pushUrlParams();
  }

  /** Called when a category badge in the product row is clicked */
  filterByCategory(p: ProductSummary): void {
    if (p.superDepartment) {
      this.selectSuper(p.superDepartment);
      if (p.department && p.department !== p.superDepartment) {
        this.selectDept(p.department);
      }
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  onQueryChange(v: string): void {
    this.query.set(v);
    this.searchQuery$.next(v);
    this._pushUrlParams();
  }

  sortIcon(field: SortField): string {
    if (this.sortField() !== field) return '⇅';
    return this.sortDir() === 'asc' ? '↑' : '↓';
  }

  trackByTpnc(_: number, p: ProductSummary): string {
    return p.tpnc;
  }

  private _pushUrlParams(): void {
    const qp: Record<string, string | null> = {
      q:     this.query().trim() || null,
      super: this.selectedSuper(),
      dept:  this.selectedDept(),
      sort:  this.sortField() !== 'name' ? this.sortField() : null,
      dir:   this.sortDir() !== 'asc' ? this.sortDir() : null,
    };
    // Remove null entries so URL stays clean
    const clean: Record<string, string> = {};
    for (const [k, v] of Object.entries(qp)) {
      if (v !== null) clean[k] = v;
    }
    this.router.navigate([], { queryParams: clean, replaceUrl: true });
  }
}
