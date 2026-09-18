import { Injectable, computed, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, catchError, map, of, tap } from 'rxjs';
import { AppConfigService } from './app-config.service';

/** One shared category, with how many products each selected store has in it. */
export interface CategoryInfo {
  id: string;
  /** The canonical path, e.g. ["Alapvető élelmiszerek", "Tejtermékek"]. */
  names: string[];
  /** The last level, which is what the filter shows. */
  name: string;
  counts: Record<string, number>;
  products: number;
}

/**
 * The shared category vocabulary.
 *
 * Categories are learned from the products the stores have in common, so the
 * list depends on which stores are selected and has to be reloaded when that
 * changes. It is legitimately empty — before the first mapping is built, or
 * for a store combination with nothing in common — and the filter hides itself
 * rather than offering a choice that would return nothing.
 */
@Injectable({ providedIn: 'root' })
export class CategoriesService {
  private http = inject(HttpClient);
  private config = inject(AppConfigService);

  readonly categories = signal<CategoryInfo[]>([]);
  readonly loaded = signal(false);
  /** The chosen category id, or '' for every category. */
  readonly selected = signal('');

  readonly available = computed(() => this.categories().length > 0);

  load(stores: string): Observable<CategoryInfo[]> {
    return this.http
      .get<{ categories: CategoryInfo[] }>(`${this.config.apiBaseUrl}/categories`, {
        params: stores ? { stores } : {},
      })
      .pipe(
        map((res) => res?.categories ?? []),
        catchError(() => of([] as CategoryInfo[])),
        tap((categories) => {
          this.categories.set(categories);
          this.loaded.set(true);
          // A category that the new store selection does not offer must not
          // stay selected, or every page would come back empty.
          if (this.selected() && !categories.some((c) => c.id === this.selected())) this.selected.set('');
        }),
      );
  }

  select(id: string): void {
    this.selected.set(this.categories().some((c) => c.id === id) ? id : '');
  }

  clear(): void {
    this.selected.set('');
  }

  /** Value for the API ``category`` query parameter ('' = no filter). */
  categoryParam(): string {
    return this.selected();
  }

  name(id: string): string {
    return this.categories().find((c) => c.id === id)?.name ?? id;
  }
}
