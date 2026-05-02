import { Component, inject, signal } from '@angular/core';
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
  readonly results    = signal<ProductSummary[]>([]);
  readonly suggestions = signal<ProductSummary[]>([]);
  readonly loading    = signal(false);
  readonly suggesting = signal(false);
  readonly error      = signal('');
  readonly searched   = signal(false);
  readonly showDropdown = signal(false);

  private suggest$ = new Subject<string>();

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
            return of({ results: [] });
          }
          this.suggesting.set(true);
          return this.products.search(term).pipe(catchError(() => of({ results: [] })));
        }),
      )
      .subscribe((res) => {
        this.suggesting.set(false);
        const items = res?.results ?? [];
        this.suggestions.set(items.slice(0, 6));
        this.showDropdown.set(items.length > 0);
      });
  }

  onInput(value: string): void {
    this.query = value;
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
    this.showDropdown.set(false);
    const q = this.query.trim();
    if (!q) return;
    this.loading.set(true);
    this.error.set('');
    this.searched.set(true);
    this.products.search(q).subscribe({
      next: (response) => {
        this.results.set(response?.results ?? []);
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(err?.error?.error || 'Search failed.');
        this.loading.set(false);
      },
    });
  }
}
