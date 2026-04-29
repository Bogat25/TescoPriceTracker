import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ProductSummary, ProductsService } from '../services/products.service';

@Component({
  selector: 'app-search',
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './search.html',
  styleUrl: './search.scss',
})
export class Search {
  private products = inject(ProductsService);

  query = '';
  readonly results = signal<ProductSummary[]>([]);
  readonly loading = signal(false);
  readonly error = signal('');
  readonly searched = signal(false);

  submit(): void {
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
