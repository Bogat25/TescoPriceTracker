import { Component, ElementRef, OnDestroy, OnInit, ViewChild, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Title } from '@angular/platform-browser';
import {
  CategoryScale, Chart, Legend, LineController, LineElement, LinearScale, PointElement, Tooltip,
} from 'chart.js';
import { Observable, forkJoin, map, of, switchMap } from 'rxjs';
import { catchError } from 'rxjs/operators';
import {
  CatalogService, GroupHistory, HistoryRow, Offer, ProductRow, bestPriceKind,
} from '../services/catalog.service';
import { StoresService } from '../services/stores.service';
import { StoreSelector } from '../shared/store-selector/store-selector';
import { StoreAlertForm } from '../shared/store-alert-form/store-alert-form';
import { TranslatePipe } from '../shared/translate.pipe';
import { storeAccent } from '../shared/store-accent';

Chart.register(LineController, LineElement, PointElement, LinearScale, CategoryScale, Legend, Tooltip);

type OfferWithText = Offer & { description?: string | null; ingredients?: string | null };
type Range = 30 | 90 | 0;

/** Lowest price of a history day: regular, promo or card. */
export function bestOfDay(row: HistoryRow): number | null {
  const values = [row.regular, row.promo, row.loyalty].filter((v): v is number => v !== null && v !== undefined);
  return values.length ? Math.min(...values) : null;
}

/** Chart labels (every date of any series) and one aligned value list per series. */
export function alignSeries(
  series: GroupHistory['series'],
  range: Range,
  today = new Date(),
): { labels: string[]; values: Record<string, (number | null)[]> } {
  const cutoff = range ? new Date(today.getTime() - range * 864e5).toISOString().slice(0, 10) : '';
  const labels = [...new Set(series.flatMap((s) => s.history.map((h) => h.date)))]
    .filter((date) => date >= cutoff)
    .sort();
  const values: Record<string, (number | null)[]> = {};
  for (const s of series) {
    const byDate = new Map(s.history.map((h) => [h.date, bestOfDay(h)]));
    values[s.ref] = labels.map((date) => byDate.get(date) ?? null);
  }
  return { labels, values };
}

/** Product page for a barcode group (/p/:groupId) or a single store offer (/o/:ref). */
@Component({
  selector: 'app-compare-page',
  imports: [DecimalPipe, RouterLink, StoreSelector, StoreAlertForm, TranslatePipe],
  templateUrl: './compare-page.html',
  styleUrl: './compare-page.scss',
})
export class ComparePage implements OnInit, OnDestroy {
  @ViewChild('historyChart') historyChart?: ElementRef<HTMLCanvasElement>;

  private route = inject(ActivatedRoute);
  private catalog = inject(CatalogService);
  private title = inject(Title);
  readonly stores = inject(StoresService);

  readonly row = signal<ProductRow | null>(null);
  readonly texts = signal<OfferWithText[]>([]);
  readonly loading = signal(true);
  readonly notFound = signal(false);
  readonly range = signal<Range>(90);
  private history: GroupHistory | null = null;
  private chart?: Chart;
  private groupId: string | null = null;
  private ref: string | null = null;
  readonly alertTarget = signal('');

  readonly primary = computed(() => this.row()?.offers[0] ?? null);
  readonly description = computed(() => this.texts().find((o) => o.description)?.description ?? null);
  readonly ingredients = computed(() => this.texts().find((o) => o.ingredients)?.ingredients ?? null);
  readonly categoryPath = computed(() => this.row()?.offers.find((o) => o.category_path.length)?.category_path ?? []);

  ngOnInit(): void {
    this.route.paramMap.subscribe((params) => {
      this.groupId = params.get('groupId');
      this.ref = params.get('ref');
      this.alertTarget.set(this.groupId ?? this.ref ?? '');
      this.load();
    });
  }

  ngOnDestroy(): void {
    this.chart?.destroy();
  }

  load(): void {
    this.loading.set(true);
    this.notFound.set(false);
    this.stores
      .load()
      .pipe(switchMap(() => this.fetch()))
      .subscribe((result) => {
        this.loading.set(false);
        if (!result) {
          this.row.set(null);
          this.notFound.set(true);
          return;
        }
        this.row.set(result.row);
        this.history = result.history;
        this.title.setTitle(`${result.row.name ?? ''} — ${this.stores.stores().map((s) => s.name).join(', ')}`);
        setTimeout(() => this.renderChart(), 0);
        this.loadTexts(result.row);
      });
  }

  private fetch(): Observable<{ row: ProductRow; history: GroupHistory } | null> {
    const stores = this.stores.storesParam();
    if (this.groupId) {
      return forkJoin({
        row: this.catalog.group(this.groupId, stores),
        history: this.catalog.groupHistory(this.groupId, stores),
      }).pipe(catchError(() => of(null)));
    }
    if (this.ref) {
      const ref = this.ref;
      return forkJoin({ offer: this.catalog.offer(ref), history: this.catalog.offerHistory(ref) }).pipe(
        map(({ offer, history }) => ({
          row: {
            group_id: offer.group_id, gtin: offer.gtin, name: offer.name, brand: offer.brand,
            image_url: offer.image_url, best_price: offer.effective_price,
            cheapest_stores: [offer.store], store_count: 1, offers: [offer],
          },
          history: { group_id: offer.group_id ?? ref, series: [{ store: offer.store, ref, history: history.history }] },
        })),
        catchError(() => of(null)),
      );
    }
    return of(null);
  }

  private loadTexts(row: ProductRow): void {
    forkJoin(row.offers.map((o) => this.catalog.offer(o.ref).pipe(catchError(() => of(null))))).subscribe(
      (offers) => this.texts.set(offers.filter((o): o is OfferWithText => o !== null)),
    );
  }

  setRange(range: Range): void {
    this.range.set(range);
    this.renderChart();
  }

  cheapestNames(row: ProductRow): string {
    return row.cheapest_stores.map((id) => this.stores.name(id)).join(', ');
  }

  kind(offer: Offer): string {
    return bestPriceKind(offer.prices) ?? 'regular';
  }

  accent(storeId: string): string {
    return storeAccent(storeId);
  }

  isCheapest(offer: Offer): boolean {
    const r = this.row();
    return !!r && r.offers.length > 1 && offer.effective_price !== null && offer.effective_price === r.best_price;
  }

  private renderChart(): void {
    const canvas = this.historyChart?.nativeElement;
    const history = this.history;
    this.chart?.destroy();
    if (!canvas || !history) return;
    const { labels, values } = alignSeries(history.series, this.range());
    const datasets = history.series.map((s) => ({
      label: this.stores.name(s.store),
      data: values[s.ref],
      borderColor: storeAccent(s.store),
      backgroundColor: storeAccent(s.store),
      tension: 0.2,
      pointRadius: labels.length > 60 ? 0 : 2,
      borderWidth: 2,
      spanGaps: true,
    }));
    this.chart = new Chart(canvas, {
      type: 'line',
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { grid: { display: false }, ticks: { maxTicksLimit: 10, autoSkip: true } },
          y: { beginAtZero: false, ticks: { callback: (v) => `${v} Ft` } },
        },
        plugins: {
          legend: { position: 'bottom' },
          tooltip: {
            callbacks: {
              label: (ctx) => ctx.parsed.y === null ? `${ctx.dataset.label}: —` : `${ctx.dataset.label}: ${Math.round(ctx.parsed.y)} Ft`,
            },
          },
        },
      },
    });
  }
}
