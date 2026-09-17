import { Component, OnInit, inject, signal, computed, HostListener } from '@angular/core';

import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap, catchError } from 'rxjs/operators';
import { of } from 'rxjs';
import { AuthService } from '../services/auth.service';
import { CatalogService, ProductRow, rowLink } from '../services/catalog.service';
import { StoresService } from '../services/stores.service';
import { StoreSelector } from '../shared/store-selector/store-selector';
import { ProductRowCard } from '../shared/product-row-card/product-row-card';
import { TranslatePipe } from '../shared/translate.pipe';

@Component({
  selector: 'app-search',
  imports: [CommonModule, FormsModule, StoreSelector, ProductRowCard, TranslatePipe],
  templateUrl: './search.html',
  styleUrl: './search.scss',
})
export class Search implements OnInit {
  private catalog = inject(CatalogService);
  readonly stores = inject(StoresService);
  private auth = inject(AuthService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);

  query = '';
  readonly allResults   = signal<ProductRow[]>([]);
  readonly results      = computed(() => this.allResults());
  readonly totalResults = signal(0);
  readonly suggestions  = signal<ProductRow[]>([]);
  readonly loading      = signal(false);
  readonly suggesting   = signal(false);
  readonly error        = signal('');
  readonly searched     = signal(false);
  readonly showDropdown = signal(false);

  /** Recommendation state */
  readonly recommendations    = signal<ProductRow[]>([]);
  readonly recommendationType = signal<'cold_start' | 'personalized'>('cold_start');
  readonly loadingRecs        = signal(false);

  /** Pagination state */
  readonly pageSize    = signal(this._calcPageSize());
  readonly currentPage = signal(0);
  // The API serves at most the first 1000 results of a query.
  readonly totalPages  = computed(() => Math.min(Math.ceil(this.totalResults() / this.pageSize()), Math.floor(1000 / this.pageSize())));
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
          return this.catalog
            .search(term, this.stores.storesParam(), 0, 6, 'text')
            .pipe(catchError(() => of({ results: [] as ProductRow[], total: 0 })));
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
      // The remembered store selection is only known once the store list loaded.
      this.stores.load().subscribe(() => this._doSearch(q, page));
    } else {
      // Load recommendations when user hasn't searched yet
      this._loadRecommendations();
    }
  }

  private _loadRecommendations(): void {
    this.loadingRecs.set(true);

    // Cold-start recommendations are public and should never be held hostage by
    // session/token state. Render them first, then replace them with the signed-in
    // user's picks when those are available. If personalization fails, keep the
    // already-rendered cold-start results instead of leaving the page blank.
    this.stores.load().pipe(
      switchMap(() => this.catalog.recommended(this.stores.storesParam(), false)),
      switchMap((coldStart) => {
        this.recommendations.set(coldStart.results ?? []);
        this.recommendationType.set(coldStart.type);
        this.loadingRecs.set(false);

        return this.auth.checkSession().pipe(
          switchMap(() => this.auth.userId()
            ? this.catalog.recommended(this.stores.storesParam(), true)
                .pipe(catchError(() => of(coldStart)))
            : of(coldStart)),
          catchError(() => of(coldStart)),
        );
      }),
    ).subscribe({
      next: (res) => {
        this.recommendations.set(res.results ?? []);
        this.recommendationType.set(res.type);
        this.loadingRecs.set(false);
      },
      error: () => {
        this.loadingRecs.set(false);
      },
    });
  }

  onInput(value: string): void {
    this.query = value;
    this._submitting = false; // user is typing again — re-enable suggestions
    this.suggest$.next(value);
  }

  pickSuggestion(row: ProductRow): void {
    this.showDropdown.set(false);
    this.suggestions.set([]);
    this.router.navigate(rowLink(row));
  }

  /** Store chips changed: repeat the current search for the new selection. */
  onStoresChanged(): void {
    if (this._lastQuery) this._doSearch(this._lastQuery, 0);
    else this._loadRecommendations();
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
    this._doSearch(this._lastQuery, page);
  }

  private _doSearch(q: string, page = 0): void {
    this.loading.set(true);
    this.error.set('');
    this.searched.set(true);
    const skip = page * this.pageSize();
    const limit = this.pageSize();
    this.catalog.search(q, this.stores.storesParam(), skip, limit).subscribe({
      next: (response) => {
        this.allResults.set(response?.results ?? []);
        this.totalResults.set(response?.total ?? 0);
        this.currentPage.set(page);
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(err?.error?.detail || 'Search failed.');
        this.loading.set(false);
      },
    });
  }
}
