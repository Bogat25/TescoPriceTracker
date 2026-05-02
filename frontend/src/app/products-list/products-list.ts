import { Component, OnInit, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { ProductsService, ProductSummary } from '../services/products.service';
import { HexIcon }   from '../shared/hex-icon/hex-icon';
import { SecLabel }  from '../shared/sec-label/sec-label';

type SortField = 'name' | 'price' | 'category';
type SortDir   = 'asc' | 'desc';

const PAGE_SIZE = 100;

@Component({
  selector: 'app-products-list',
  imports: [CommonModule, RouterLink, FormsModule, HexIcon, SecLabel],
  templateUrl: './products-list.html',
  styleUrl: './products-list.scss',
})
export class ProductsList implements OnInit {
  private productsApi = inject(ProductsService);

  readonly allProducts = signal<ProductSummary[]>([]);
  readonly loading     = signal(true);
  readonly loadingMore = signal(false);
  readonly error       = signal('');
  readonly query       = signal('');
  readonly sortField   = signal<SortField>('name');
  readonly sortDir     = signal<SortDir>('asc');
  readonly total       = signal(0);
  private  skip        = 0;

  readonly hasMore = computed(() => this.allProducts().length < this.total());

  readonly filtered = computed(() => {
    const q = this.query().toLowerCase().trim();
    let list = q
      ? this.allProducts().filter(p =>
          (p.name  ?? '').toLowerCase().includes(q) ||
          p.tpnc.includes(q) ||
          (p.category ?? '').toLowerCase().includes(q))
      : this.allProducts();

    const f = this.sortField();
    const d = this.sortDir() === 'asc' ? 1 : -1;
    return [...list].sort((a, b) => {
      if (f === 'price') {
        const pa = a.currentPrice ?? 0;
        const pb = b.currentPrice ?? 0;
        return d * (pa - pb);
      }
      if (f === 'category') {
        return d * (a.category ?? '').localeCompare(b.category ?? '');
      }
      return d * (a.name ?? a.tpnc).localeCompare(b.name ?? b.tpnc);
    });
  });

  ngOnInit(): void {
    this.loadPage();
  }

  private loadPage(): void {
    this.productsApi.browse(this.skip, PAGE_SIZE).subscribe({
      next: (res) => {
        this.allProducts.update(prev => [...prev, ...res.results]);
        this.total.set(res.total);
        this.skip += res.results.length;
        this.loading.set(false);
        this.loadingMore.set(false);
      },
      error: () => {
        this.error.set('Could not load products.');
        this.loading.set(false);
        this.loadingMore.set(false);
      },
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
      this.sortDir.set('asc');
    }
  }

  sortIcon(field: SortField): string {
    if (this.sortField() !== field) return '⇅';
    return this.sortDir() === 'asc' ? '↑' : '↓';
  }

  trackByTpnc(_: number, p: ProductSummary): string {
    return p.tpnc;
  }
}
