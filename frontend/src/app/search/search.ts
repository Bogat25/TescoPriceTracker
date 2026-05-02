import { Component, inject, signal, computed, HostListener } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
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
export class Search {
  private products = inject(ProductsService);
  private router = inject(Router);

  query = '';
  readonly results     = signal<ProductSummary[]>([]);
  readonly totalResults = signal(0);
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
    // Rough heuristic: each result row ~72px tall; reserve 280px for header/pagination
    return Math.max(10, Math.min(50, Math.floor((h - 280) / 72)));
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
    this._lastQuery = q;
    this.currentPage.set(0);
    this._doSearch(q, 0);
  }

  goToPage(page: number): void {
    if (page < 0 || page >= this.totalPages()) return;
    this.currentPage.set(page);
    this._doSearch(this._lastQuery, page);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  private _doSearch(q: string, page: number): void {
    this.loading.set(true);
    this.error.set('');
    this.searched.set(true);
    const skip = page * this.pageSize();
    this.products.searchPaged(q, skip, this.pageSize()).subscribe({
      next: (response) => {
        this.results.set(response?.results ?? []);
        this.totalResults.set(response?.total ?? 0);
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(err?.error?.error || 'Search failed.');
        this.loading.set(false);
      },
    });
  }
}
