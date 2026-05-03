import { Component, OnInit, inject, signal, computed, HostListener } from '@angular/core';

import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap, catchError } from 'rxjs/operators';
import { of } from 'rxjs';
import { ProductSummary, ProductsService } from '../services/products.service';

@Component({
  selector: 'app-search',
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './search.html',
  styleUrl: './search.scss',
})
export class Search implements OnInit {
  private products = inject(ProductsService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);

  query = '';
  readonly allResults   = signal<ProductSummary[]>([]);
  readonly results      = computed(() => {
    const size  = this.pageSize();
    const start = this.currentPage() * size;
    return this.allResults().slice(start, start + size);
  });
  readonly totalResults = computed(() => this.allResults().length);
  readonly suggestions  = signal<ProductSummary[]>([]);
  readonly loading      = signal(false);
  readonly suggesting   = signal(false);
  readonly error        = signal('');
  readonly searched     = signal(false);
  readonly showDropdown = signal(false);

  /** Pagination state */
  readonly pageSize    = signal(this._calcPageSize());
  readonly currentPage = signal(0);
  readonly totalPages  = computed(() => Math.ceil(this.totalResults() / this.pageSize()));
  readonly pageNumbers = computed(() => Array.from({ length: this.totalPages() }, (_, i) => i));

  private _lastQuery = '';
  /** True once the user has pressed Enter — suppresses any in-flight suggestion results. */
  private _submitting = false;

  private suggest$ = new Subject<string>();

  @HostListener('window:resize')
  onResize(): void {
    this.pageSize.set(this._calcPageSize());
  }

  private _calcPageSize(): number {
    const h = window.innerHeight ?? 800;
    return Math.max(64, Math.min(94, Math.floor((h - 280) / 72)));
  }

  constructor() {
    this.suggest$
      .pipe(
        debounceTime(220),
        distinctUntilChanged(),
        switchMap((q) => {
          const term = q.trim();
          if (term.length < 2) {
            this.suggesting.set(false);
            this.suggestions.set([]);
            this.showDropdown.set(false);
            return of({ results: [], total: 0 });
          }
          this.suggesting.set(true);
          return this.products.searchPaged(term, 0, 6).pipe(catchError(() => of({ results: [], total: 0 })));
        }),
      )
      .subscribe((res) => {
        this.suggesting.set(false);
        if (this._submitting) return; // user already pressed Enter — discard suggestions
        const items = res?.results ?? [];
        this.suggestions.set(items.slice(0, 6));
        this.showDropdown.set(items.length > 0);
      });
  }

  ngOnInit(): void {
    const q         = this.route.snapshot.queryParamMap.get('q') ?? '';
    const pageParam = parseInt(this.route.snapshot.queryParamMap.get('page') ?? '1', 10);
    const page      = Number.isFinite(pageParam) && pageParam > 1 ? pageParam - 1 : 0;
    if (q.trim()) {
      this.query = q;
      this._lastQuery = q;
      this._doSearch(q, page);
    }
  }

  onInput(value: string): void {
    this.query = value;
    this._submitting = false; // user is typing again — re-enable suggestions
    this.suggest$.next(value);
  }

  pickSuggestion(p: ProductSummary): void {
    this.showDropdown.set(false);
    this.suggestions.set([]);
    this.router.navigate(['/products', p.tpnc]);
  }

  closeDropdown(): void {
    // Small delay so click events on items fire first
    setTimeout(() => this.showDropdown.set(false), 150);
  }

  submit(): void {
    this._submitting = true;
    this.showDropdown.set(false);
    this.suggestions.set([]);
    const q = this.query.trim();
    if (!q) return;
    this.currentPage.set(0);
    // Push query into URL (no page param = page 1)
    this.router.navigate([], { queryParams: { q }, replaceUrl: false });
    this._lastQuery = q;
    this._doSearch(q);
  }

  goToPage(page: number): void {
    if (page < 0 || page >= this.totalPages()) return;
    this.currentPage.set(page);
    // Update URL: page is 1-indexed; omit the param on the first page
    this.router.navigate([], {
      queryParams: { q: this._lastQuery, ...(page > 0 ? { page: page + 1 } : {}) },
      replaceUrl: true,
    });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  private _doSearch(q: string, restorePage = 0): void {
    this.loading.set(true);
    this.error.set('');
    this.searched.set(true);
    // Fetch all matching results at once; client-side pagination handles paging
    this.products.searchPaged(q, 0, 10000).subscribe({
      next: (response) => {
        this.allResults.set(response?.results ?? []);
        if (restorePage > 0) {
          const clamped = Math.min(restorePage, Math.max(0, this.totalPages() - 1));
          this.currentPage.set(clamped);
        }
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(err?.error?.error || 'Search failed.');
        this.loading.set(false);
      },
    });
  }
}
