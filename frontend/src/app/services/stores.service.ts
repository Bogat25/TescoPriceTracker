import { Injectable, computed, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, catchError, map, of, shareReplay, tap } from 'rxjs';
import { AppConfigService } from './app-config.service';

export interface StoreInfo {
  id: string;
  name: string;
  order: number;
  website: string;
}

const STORAGE_KEY = 'pt_selected_stores';

function readStored(): string[] | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === 'string') : null;
  } catch {
    return null;
  }
}

function writeStored(ids: string[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
  } catch {
    // Private mode or blocked storage: the selection just is not remembered.
  }
}

/**
 * Stores switched on in the backend registry, and the visitor's selection.
 *
 * The selection is remembered per browser. An empty ``storesParam`` means
 * "every enabled store", so a newly enabled store shows up for visitors who
 * never narrowed their selection.
 */
@Injectable({ providedIn: 'root' })
export class StoresService {
  private http = inject(HttpClient);
  private config = inject(AppConfigService);

  readonly stores = signal<StoreInfo[]>([]);
  readonly loaded = signal(false);
  private readonly chosen = signal<string[] | null>(readStored());

  /** Selected store IDs in registry order; all enabled stores when nothing is narrowed. */
  readonly selected = computed(() => {
    const enabled = this.stores().map((s) => s.id);
    const chosen = this.chosen();
    const valid = chosen ? enabled.filter((id) => chosen.includes(id)) : [];
    return valid.length ? valid : enabled;
  });

  /** Only offer a choice when there is more than one store. */
  readonly showSelector = computed(() => this.stores().length > 1);

  /** Value for the API ``stores`` query parameter ('' = every enabled store). */
  readonly storesParam = computed(() => {
    const selected = this.selected();
    return selected.length === this.stores().length ? '' : selected.join(',');
  });

  private request$?: Observable<StoreInfo[]>;

  load(): Observable<StoreInfo[]> {
    if (!this.request$) {
      this.request$ = this.http
        .get<{ stores: StoreInfo[] }>(`${this.config.tescoApiBaseUrl}/stores`)
        .pipe(
          map((res) => [...(res?.stores ?? [])].sort((a, b) => a.order - b.order)),
          catchError(() => of([] as StoreInfo[])),
          tap((stores) => {
            this.stores.set(stores);
            this.loaded.set(true);
          }),
          shareReplay(1),
        );
    }
    return this.request$;
  }

  name(id: string): string {
    return this.stores().find((s) => s.id === id)?.name ?? id;
  }

  isSelected(id: string): boolean {
    return this.selected().includes(id);
  }

  /** Toggle one store; the last selected store cannot be switched off. */
  toggle(id: string): void {
    const current = this.selected();
    const next = current.includes(id) ? current.filter((s) => s !== id) : [...current, id];
    if (!next.length) return;
    this.chosen.set(next);
    writeStored(next);
  }

  selectAll(): void {
    this.chosen.set(null);
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
  }
}
