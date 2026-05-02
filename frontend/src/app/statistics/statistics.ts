import {
  AfterViewInit,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  ElementRef,
  OnDestroy,
  ViewChild,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Subject, debounceTime, forkJoin, of, switchMap } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { HexIcon }   from '../shared/hex-icon/hex-icon';
import { HexKpi }    from '../shared/hex-kpi/hex-kpi';
import { SecLabel }  from '../shared/sec-label/sec-label';
import {
  ArcElement,
  BarController,
  BarElement,
  CategoryScale,
  Chart,
  DoughnutController,
  Filler,
  Legend,
  LineController,
  LineElement,
  LinearScale,
  PointElement,
  PolarAreaController,
  RadialLinearScale,
  Tooltip,
} from 'chart.js';
import {
  PriceEntry,
  ProductResponse,
  ProductStats,
  ProductSummary,
  ProductsService,
  toSummary,
} from '../services/products.service';
import {
  BestShoppingDay,
  CategoryDiff,
  DiscountByWeekday,
  GlobalAvg,
  Inflation30d,
  PlatformStatsService,
  PriceDrop,
  PriceIndexPoint,
  PriceTier,
  ProductVolume,
  TopDiscountGroup,
  VolatilityTier,
} from '../services/platform-stats.service';

Chart.register(
  LineController,
  BarController,
  DoughnutController,
  PolarAreaController,
  LineElement,
  BarElement,
  ArcElement,
  PointElement,
  LinearScale,
  CategoryScale,
  RadialLinearScale,
  Tooltip,
  Legend,
  Filler,
);

type Channel = 'normal' | 'discount' | 'clubcard';

const CHANNEL_COLOURS: Record<Channel, { border: string; bg: string }> = {
  normal: { border: 'rgb(59, 130, 246)', bg: 'rgba(59, 130, 246, 0.15)' },
  discount: { border: 'rgb(249, 115, 22)', bg: 'rgba(249, 115, 22, 0.15)' },
  clubcard: { border: 'rgb(234, 179, 8)', bg: 'rgba(234, 179, 8, 0.20)' },
};

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

interface KpiAgg {
  current?: number;
  min?: number;
  max?: number;
  avg?: number;
  clubcardMin?: number;
  savingsPct?: number;
  entryCount: number;
  promoCount: number;
  firstSeen?: Date;
  lastSeen?: Date;
  volatility?: number;
  trendPct?: number;
  bestMonth?: string;
  daysTracked?: number;
  promoFreqPct?: number;
  priceChanges?: number;
  clubcardTotalSavings?: number;
}

@Component({
  selector: 'app-statistics',
  imports: [CommonModule, FormsModule, RouterLink, HexIcon, HexKpi, SecLabel],
  templateUrl: './statistics.html',
  styleUrl: './statistics.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Statistics implements AfterViewInit, OnDestroy {
  // ─── Platform overview chart canvases ───────────────────────────────
  @ViewChild('platformIndexChart') platformIndexChart?: ElementRef<HTMLCanvasElement>;
  @ViewChild('platformTiersChart') platformTiersChart?: ElementRef<HTMLCanvasElement>;
  @ViewChild('platformCategoryChart') platformCategoryChart?: ElementRef<HTMLCanvasElement>;
  @ViewChild('platformWeekdayChart') platformWeekdayChart?: ElementRef<HTMLCanvasElement>;
  @ViewChild('platformVolatilityChart') platformVolatilityChart?: ElementRef<HTMLCanvasElement>;
  @ViewChild('platformTopDiscountsChart') platformTopDiscountsChart?: ElementRef<HTMLCanvasElement>;

  // ─── Product-specific chart canvases ────────────────────────────────
  @ViewChild('lineChart') lineChart?: ElementRef<HTMLCanvasElement>;
  @ViewChild('channelDoughnut') channelDoughnut?: ElementRef<HTMLCanvasElement>;
  @ViewChild('promoDoughnut') promoDoughnut?: ElementRef<HTMLCanvasElement>;
  @ViewChild('monthlyBar') monthlyBar?: ElementRef<HTMLCanvasElement>;
  @ViewChild('savingsBar') savingsBar?: ElementRef<HTMLCanvasElement>;
  @ViewChild('polarChart') polarChart?: ElementRef<HTMLCanvasElement>;
  @ViewChild('distributionBar') distributionBar?: ElementRef<HTMLCanvasElement>;
  @ViewChild('yoyBar') yoyBar?: ElementRef<HTMLCanvasElement>;
  @ViewChild('deltaBar') deltaBar?: ElementRef<HTMLCanvasElement>;
  @ViewChild('cumulativeSavings') cumulativeSavings?: ElementRef<HTMLCanvasElement>;
  @ViewChild('promoDensityBar') promoDensityBar?: ElementRef<HTMLCanvasElement>;

  private products = inject(ProductsService);
  private platformStats = inject(PlatformStatsService);
  private cdr = inject(ChangeDetectorRef);

  // ─── Tab state ──────────────────────────────────────────────────────
  readonly activeTab = signal<'overview' | 'product'>('overview');

  // ─── Platform overview signals ──────────────────────────────────────
  readonly platformLoading = signal(false);
  readonly platformError = signal('');
  readonly priceIndex = signal<PriceIndexPoint[]>([]);
  readonly productVolume = signal<ProductVolume | null>(null);
  readonly priceTiers = signal<PriceTier[]>([]);
  readonly categoryDiff = signal<CategoryDiff | null>(null);
  readonly topDiscounts = signal<TopDiscountGroup[]>([]);
  readonly bestShoppingDay = signal<BestShoppingDay | null>(null);
  readonly discountByWeekday = signal<DiscountByWeekday[]>([]);
  readonly volatilityTiers = signal<VolatilityTier[]>([]);
  readonly globalAvg = signal<GlobalAvg | null>(null);
  readonly inflation30d = signal<Inflation30d | null>(null);
  readonly priceDropsToday = signal<PriceDrop[]>([]);

  // ─── Product analysis signals ──────────────────────────────────────

  readonly query = signal('');
  readonly suggestions = signal<ProductSummary[]>([]);
  readonly searching = signal(false);
  readonly loading = signal(false);
  readonly error = signal('');
  readonly selected = signal<ProductResponse | null>(null);
  readonly selectedSummary = computed(() => {
    const raw = this.selected();
    return raw ? toSummary(raw) : null;
  });
  readonly kpi = signal<KpiAgg>({ entryCount: 0, promoCount: 0 });
  readonly insights = signal<string[]>([]);
  readonly serverStats = signal<ProductStats | null>(null);

  private searchInput$ = new Subject<string>();
  private charts: Chart[] = [];
  private viewReady = false;

  constructor() {
    this.searchInput$
      .pipe(
        debounceTime(300),
        switchMap((q) => {
          const term = q.trim();
          if (term.length < 2) {
            this.searching.set(false);
            return of<ProductResponse[]>([]);
          }
          this.searching.set(true);
          return this.products.searchRaw(term).pipe(
            catchError(() => of<ProductResponse[]>([])),
          );
        }),
      )
      .subscribe((arr) => {
        this.searching.set(false);
        this.suggestions.set((arr ?? []).slice(0, 10).map(toSummary));
      });
  }

  ngAfterViewInit(): void {
    this.viewReady = true;
    this.loadPlatformStats();
  }

  ngOnDestroy(): void {
    this.destroyCharts();
    for (const c of this.platformCharts) c.destroy();
    this.platformCharts = [];
    this.searchInput$.complete();
  }

  switchTab(tab: 'overview' | 'product'): void {
    this.activeTab.set(tab);
    if (tab === 'overview') {
      this.cdr.detectChanges();
      setTimeout(() => this.renderPlatformCharts(), 0);
    }
  }

  // ─── Platform overview loading ──────────────────────────────────────

  private loadPlatformStats(): void {
    this.platformLoading.set(true);
    this.platformError.set('');

    forkJoin({
      priceIndex: this.platformStats.priceIndex().pipe(catchError(() => of([]))),
      productVolume: this.platformStats.productVolume().pipe(catchError(() => of(null))),
      priceTiers: this.platformStats.priceTiers().pipe(catchError(() => of([]))),
      categoryDiff: this.platformStats.categoryDiff().pipe(catchError(() => of(null))),
      topDiscounts: this.platformStats.topDiscounts().pipe(catchError(() => of([]))),
      bestShoppingDay: this.platformStats.bestShoppingDay().pipe(catchError(() => of(null))),
      discountByWeekday: this.platformStats.discountByWeekday().pipe(catchError(() => of([]))),
      volatilityTiers: this.platformStats.volatility().pipe(catchError(() => of([]))),
      globalAvg: this.platformStats.globalAvg().pipe(catchError(() => of(null))),
      inflation30d: this.platformStats.inflation30d().pipe(catchError(() => of(null))),
      priceDropsToday: this.platformStats.priceDropsToday().pipe(catchError(() => of([]))),
    }).subscribe({
      next: (data) => {
        this.priceIndex.set(data.priceIndex as PriceIndexPoint[]);
        this.productVolume.set(data.productVolume as ProductVolume | null);
        this.priceTiers.set(data.priceTiers as PriceTier[]);
        this.categoryDiff.set(data.categoryDiff as CategoryDiff | null);
        this.topDiscounts.set(data.topDiscounts as TopDiscountGroup[]);
        this.bestShoppingDay.set(data.bestShoppingDay as BestShoppingDay | null);
        this.discountByWeekday.set(data.discountByWeekday as DiscountByWeekday[]);
        this.volatilityTiers.set(data.volatilityTiers as VolatilityTier[]);
        this.globalAvg.set(data.globalAvg as GlobalAvg | null);
        this.inflation30d.set(data.inflation30d as Inflation30d | null);
        this.priceDropsToday.set(data.priceDropsToday as PriceDrop[]);
        this.platformLoading.set(false);
        this.cdr.detectChanges();
        setTimeout(() => this.renderPlatformCharts(), 0);
      },
      error: () => {
        this.platformError.set('Failed to load platform statistics.');
        this.platformLoading.set(false);
      },
    });
  }

  private platformCharts: Chart[] = [];

  private renderPlatformCharts(): void {
    for (const c of this.platformCharts) c.destroy();
    this.platformCharts = [];

    this.renderPriceIndexChart();
    this.renderPriceTiersChart();
    this.renderCategoryDiffChart();
    this.renderWeekdayChart();
    this.renderVolatilityChart();
    this.renderTopDiscountsChart();
  }

  private renderPriceIndexChart(): void {
    const canvas = this.platformIndexChart?.nativeElement;
    const data = this.priceIndex();
    if (!canvas || !data.length) return;

    const labels = data.map((d) => d.date);
    const values = data.map((d) => d.index);

    this.platformCharts.push(
      new Chart(canvas, {
        type: 'line',
        data: {
          labels,
          datasets: [{
            label: 'Price Index',
            data: values,
            borderColor: 'rgb(59, 130, 246)',
            backgroundColor: 'rgba(59, 130, 246, 0.1)',
            fill: true,
            tension: 0.3,
            pointRadius: 0,
            pointHoverRadius: 4,
            borderWidth: 2,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          scales: {
            x: { grid: { display: false }, ticks: { maxTicksLimit: 12, autoSkip: true } },
            y: {
              ticks: { callback: (v) => `${v}` },
            },
          },
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: (ctx) => `Index: ${Number(ctx.parsed.y).toFixed(1)} (base=100)`,
              },
            },
          },
        },
      }),
    );
  }

  private renderPriceTiersChart(): void {
    const canvas = this.platformTiersChart?.nativeElement;
    const data = this.priceTiers();
    if (!canvas || !data.length) return;

    this.platformCharts.push(
      new Chart(canvas, {
        type: 'bar',
        data: {
          labels: data.map((t) => t.tier),
          datasets: [{
            label: 'Products',
            data: data.map((t) => t.count),
            backgroundColor: 'rgba(59, 130, 246, 0.6)',
            borderColor: 'rgb(59, 130, 246)',
            borderWidth: 1,
            borderRadius: 4,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: { grid: { display: false } },
            y: { beginAtZero: true },
          },
          plugins: { legend: { display: false } },
        },
      }),
    );
  }

  private renderCategoryDiffChart(): void {
    const canvas = this.platformCategoryChart?.nativeElement;
    const diff = this.categoryDiff();
    if (!canvas || !diff) return;

    const labels = ['Normal', 'Discount', 'Clubcard'];
    const values = [diff.avg_normal ?? 0, diff.avg_discount ?? 0, diff.avg_clubcard ?? 0];
    if (!values.some((v) => v > 0)) return;

    this.platformCharts.push(
      new Chart(canvas, {
        type: 'bar',
        data: {
          labels,
          datasets: [{
            label: 'Average price (Ft)',
            data: values,
            backgroundColor: [
              'rgba(59, 130, 246, 0.6)',
              'rgba(249, 115, 22, 0.6)',
              'rgba(234, 179, 8, 0.6)',
            ],
            borderColor: [
              'rgb(59, 130, 246)',
              'rgb(249, 115, 22)',
              'rgb(234, 179, 8)',
            ],
            borderWidth: 1,
            borderRadius: 4,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: { grid: { display: false } },
            y: { beginAtZero: true, ticks: { callback: (v) => `${v} Ft` } },
          },
          plugins: { legend: { display: false } },
        },
      }),
    );
  }

  private renderWeekdayChart(): void {
    const canvas = this.platformWeekdayChart?.nativeElement;
    const data = this.discountByWeekday();
    if (!canvas || !data.length) return;

    this.platformCharts.push(
      new Chart(canvas, {
        type: 'bar',
        data: {
          labels: data.map((d) => d.weekday.substring(0, 3)),
          datasets: [{
            label: 'Avg discount %',
            data: data.map((d) => d.avg_pct_off),
            backgroundColor: 'rgba(16, 185, 129, 0.6)',
            borderColor: 'rgb(16, 185, 129)',
            borderWidth: 1,
            borderRadius: 4,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: { grid: { display: false } },
            y: { beginAtZero: true, ticks: { callback: (v) => `${v}%` } },
          },
          plugins: { legend: { display: false } },
        },
      }),
    );
  }

  private renderVolatilityChart(): void {
    const canvas = this.platformVolatilityChart?.nativeElement;
    const data = this.volatilityTiers();
    if (!canvas || !data.length) return;

    this.platformCharts.push(
      new Chart(canvas, {
        type: 'bar',
        data: {
          labels: data.map((d) => d.tier),
          datasets: [{
            label: 'Avg volatility (std-dev)',
            data: data.map((d) => d.avg_volatility),
            backgroundColor: 'rgba(239, 68, 68, 0.5)',
            borderColor: 'rgb(239, 68, 68)',
            borderWidth: 1,
            borderRadius: 4,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: { grid: { display: false } },
            y: { beginAtZero: true, ticks: { callback: (v) => `${v} Ft` } },
          },
          plugins: { legend: { display: false } },
        },
      }),
    );
  }

  private renderTopDiscountsChart(): void {
    const canvas = this.platformTopDiscountsChart?.nativeElement;
    const data = this.topDiscounts();
    if (!canvas || !data.length) return;

    // Show top 15 discount tiers
    const top = data.slice(0, 15);
    this.platformCharts.push(
      new Chart(canvas, {
        type: 'bar',
        data: {
          labels: top.map((d) => `${d.pct_off}% off`),
          datasets: [{
            label: 'Products at this discount',
            data: top.map((d) => d.products.length),
            backgroundColor: 'rgba(168, 85, 247, 0.5)',
            borderColor: 'rgb(168, 85, 247)',
            borderWidth: 1,
            borderRadius: 4,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          indexAxis: 'y',
          scales: {
            x: { beginAtZero: true },
            y: { grid: { display: false } },
          },
          plugins: { legend: { display: false } },
        },
      }),
    );
  }

  onSearchInput(value: string): void {
    this.query.set(value);
    this.searchInput$.next(value);
  }

  pick(summary: ProductSummary): void {
    this.query.set(summary.name ?? summary.tpnc);
    this.suggestions.set([]);
    this.load(summary.tpnc);
  }

  load(tpnc: string): void {
    this.loading.set(true);
    this.error.set('');
    this.serverStats.set(null);
    this.insights.set([]);

    const product$ = this.products.getRaw(tpnc);
    const stats$ = this.products.stats(tpnc).pipe(catchError(() => of(null)));

    forkJoin({ product: product$, stats: stats$ }).subscribe({
      next: ({ product, stats }) => {
        this.selected.set(product);
        this.serverStats.set(stats as ProductStats | null);
        const kpi = this.computeKpis(product);
        this.kpi.set(kpi);
        this.insights.set(this.computeInsights(product, kpi));
        this.loading.set(false);
        // Force change detection so canvas elements are created before rendering charts.
        this.cdr.detectChanges();
        setTimeout(() => this.renderAll(product), 0);
      },
      error: (err) => {
        this.error.set(err?.error?.error || 'Failed to load product data.');
        this.loading.set(false);
        this.selected.set(null);
        this.destroyCharts();
      },
    });
  }

  trendLabel(pct: number | undefined): string {
    if (pct === undefined) return '—';
    if (Math.abs(pct) < 1) return '→ Stable';
    return pct > 0 ? `↑ +${pct.toFixed(1)}%` : `↓ ${pct.toFixed(1)}%`;
  }

  trendClass(pct: number | undefined): string {
    if (pct === undefined || Math.abs(pct) < 1) return 'opacity-60';
    return pct > 0 ? 'text-error' : 'text-success';
  }

  volatilityLabel(v: number | undefined): string {
    if (v === undefined) return '—';
    if (v < 3) return 'Very stable';
    if (v < 8) return 'Low';
    if (v < 15) return 'Moderate';
    return 'High';
  }

  volatilityClass(v: number | undefined): string {
    if (v === undefined) return 'opacity-60';
    if (v < 3) return 'text-success';
    if (v < 8) return 'text-info';
    if (v < 15) return 'text-warning';
    return 'text-error';
  }

  buySignalLabel(kpi: KpiAgg): string {
    if (kpi.current === undefined || kpi.avg === undefined) return '—';
    const vsAvg = ((kpi.current - kpi.avg) / kpi.avg) * 100;
    if (kpi.current === kpi.min) return '🔥 All-time low!';
    if (vsAvg < -8) return '✅ Below average';
    if (vsAvg > 8) return '⚠️ Above average';
    return '➡️ Near average';
  }

  buySignalClass(kpi: KpiAgg): string {
    if (kpi.current === kpi.min) return 'text-success font-bold';
    if (kpi.current === undefined || kpi.avg === undefined) return 'opacity-60';
    const vsAvg = ((kpi.current - kpi.avg) / kpi.avg) * 100;
    if (vsAvg < -8) return 'text-success';
    if (vsAvg > 8) return 'text-warning';
    return '';
  }

  // ───────── KPI aggregation ─────────
  private computeKpis(p: ProductResponse): KpiAgg {
    const all = this.allEntries(p);
    if (!all.length) return { entryCount: 0, promoCount: 0 };

    const prices = all.map((e) => e.price).filter((n): n is number => Number.isFinite(n));
    const clubcardPrices = (p.price_history.clubcard ?? [])
      .map((e) => e.price)
      .filter((n): n is number => Number.isFinite(n));
    const min = prices.length ? Math.min(...prices) : undefined;
    const max = prices.length ? Math.max(...prices) : undefined;
    const avg = prices.length ? prices.reduce((a, b) => a + b, 0) / prices.length : undefined;
    const current = this.parseNumber(p.last_scraped_price);
    const clubcardMin = clubcardPrices.length ? Math.min(...clubcardPrices) : undefined;
    const savingsPct =
      max !== undefined && clubcardMin !== undefined && max > 0
        ? ((max - clubcardMin) / max) * 100
        : undefined;
    const promoCount = all.filter((e) => !!e.promo_id || !!e.promo_desc).length;

    const dates = all
      .map((e) => new Date(e.start_date).getTime())
      .filter((n) => Number.isFinite(n));
    const firstSeen = dates.length ? new Date(Math.min(...dates)) : undefined;
    const lastSeen = dates.length ? new Date(Math.max(...dates)) : undefined;

    // Volatility: coefficient of variation %
    const stdDev =
      avg !== undefined && prices.length >= 2
        ? Math.sqrt(prices.reduce((a, b) => a + Math.pow(b - avg, 2), 0) / prices.length)
        : undefined;
    const volatility = avg && stdDev !== undefined ? (stdDev / avg) * 100 : undefined;

    // Trend: compare last 30 days vs prior 30 days on normal channel
    const normalEntries = (p.price_history.normal ?? [])
      .filter((e) => Number.isFinite(new Date(e.start_date).getTime()))
      .sort((a, b) => new Date(a.start_date).getTime() - new Date(b.start_date).getTime());
    const now = Date.now();
    const DAY = 24 * 3600 * 1000;
    const recent = normalEntries.filter((e) => now - new Date(e.start_date).getTime() < 30 * DAY);
    const prior = normalEntries.filter((e) => {
      const age = now - new Date(e.start_date).getTime();
      return age >= 30 * DAY && age < 60 * DAY;
    });
    const recentAvg = recent.length ? recent.reduce((a, b) => a + b.price, 0) / recent.length : undefined;
    const priorAvg = prior.length ? prior.reduce((a, b) => a + b.price, 0) / prior.length : undefined;
    const trendPct =
      recentAvg !== undefined && priorAvg !== undefined && priorAvg > 0
        ? ((recentAvg - priorAvg) / priorAvg) * 100
        : undefined;

    // Best buying month (calendar month with lowest historical avg price)
    const byCalMonth = new Map<number, number[]>();
    for (const e of all) {
      const d = new Date(e.start_date);
      if (!Number.isFinite(d.getTime())) continue;
      const arr = byCalMonth.get(d.getMonth()) ?? [];
      arr.push(e.price);
      byCalMonth.set(d.getMonth(), arr);
    }
    let bestMonth: string | undefined;
    let bestMonthAvg = Infinity;
    for (const [m, arr] of byCalMonth) {
      const mAvg = arr.reduce((a, b) => a + b, 0) / arr.length;
      if (mAvg < bestMonthAvg) {
        bestMonthAvg = mAvg;
        bestMonth = MONTH_NAMES[m];
      }
    }

    const daysTracked = firstSeen
      ? Math.round((Date.now() - firstSeen.getTime()) / DAY)
      : undefined;

    const promoFreqPct = all.length > 0 ? (promoCount / all.length) * 100 : undefined;

    // Count sequential price changes on the normal channel
    let priceChanges = 0;
    for (let i = 1; i < normalEntries.length; i++) {
      if (normalEntries[i].price !== normalEntries[i - 1].price) priceChanges++;
    }

    // Accumulated Clubcard savings vs closest normal price
    const normSeries = this.channelSeries(p.price_history.normal ?? []);
    const clubSeries = this.channelSeries(p.price_history.clubcard ?? []);
    let clubcardTotalSavings = 0;
    if (normSeries.length && clubSeries.length) {
      for (const cc of clubSeries) {
        const closest = normSeries.reduce((best, cur) =>
          Math.abs(cur.x - cc.x) < Math.abs(best.x - cc.x) ? cur : best,
        );
        if (closest.y > cc.y) clubcardTotalSavings += closest.y - cc.y;
      }
    }

    return {
      current, min, max, avg, clubcardMin, savingsPct,
      entryCount: all.length, promoCount,
      firstSeen, lastSeen,
      volatility, trendPct, bestMonth, daysTracked,
      promoFreqPct, priceChanges,
      clubcardTotalSavings: clubcardTotalSavings > 0 ? clubcardTotalSavings : undefined,
    };
  }

  private computeInsights(p: ProductResponse, kpi: KpiAgg): string[] {
    const out: string[] = [];

    if (kpi.current !== undefined && kpi.min !== undefined && kpi.current === kpi.min) {
      out.push(`This is the all-time lowest recorded price — a great time to buy.`);
    } else if (kpi.current !== undefined && kpi.avg !== undefined && kpi.avg > 0) {
      const vsAvg = ((kpi.current - kpi.avg) / kpi.avg) * 100;
      if (vsAvg < -8) out.push(`Current price is ${Math.abs(vsAvg).toFixed(1)}% below the historical average — currently a great deal.`);
      else if (vsAvg > 8) out.push(`Current price is ${vsAvg.toFixed(1)}% above the historical average — consider waiting for a discount.`);
    }

    if (kpi.trendPct !== undefined) {
      if (kpi.trendPct > 5) out.push(`Price is up ${kpi.trendPct.toFixed(1)}% over the last 30 days vs the prior period — momentum is rising.`);
      else if (kpi.trendPct < -5) out.push(`Price has fallen ${Math.abs(kpi.trendPct).toFixed(1)}% over the last 30 days — downward momentum.`);
      else out.push(`Price has been stable over the last 30 days (${kpi.trendPct >= 0 ? '+' : ''}${kpi.trendPct.toFixed(1)}%).`);
    }

    if (kpi.bestMonth) {
      out.push(`Historically, ${kpi.bestMonth} has the lowest average prices — worth waiting if the timing works.`);
    }

    if (kpi.savingsPct !== undefined && kpi.savingsPct > 0) {
      out.push(`Clubcard delivers up to ${kpi.savingsPct.toFixed(1)}% off vs. the highest normal price on record.`);
    }

    if (kpi.clubcardTotalSavings !== undefined) {
      out.push(`Across all tracked Clubcard entries, members would have saved a total of ${kpi.clubcardTotalSavings.toFixed(2)} Ft vs. normal pricing.`);
    }

    if (kpi.promoFreqPct !== undefined) {
      if (kpi.promoFreqPct > 50) out.push(`This product is on promotion more than half the time (${kpi.promoFreqPct.toFixed(0)}%) — you can usually afford to wait.`);
      else if (kpi.promoFreqPct > 25) out.push(`Promotions occur in ${kpi.promoFreqPct.toFixed(0)}% of price records — worth keeping an alert active.`);
      else if (kpi.promoFreqPct < 5 && kpi.promoCount > 0) out.push(`Promotions are rare (${kpi.promoFreqPct.toFixed(0)}% of records) — grab it when it goes on sale.`);
    }

    if (kpi.volatility !== undefined) {
      if (kpi.volatility > 15) out.push(`Price is highly volatile (${kpi.volatility.toFixed(1)}% CV) — set an alert to catch the next dip.`);
      else if (kpi.volatility < 3 && kpi.entryCount > 5) out.push(`Price is extremely stable (${kpi.volatility.toFixed(1)}% CV) — unlikely to change significantly.`);
    }

    return out;
  }

  private allEntries(p: ProductResponse): PriceEntry[] {
    const { normal = [], discount = [], clubcard = [] } = p.price_history ?? {};
    return [...normal, ...discount, ...clubcard];
  }

  private parseNumber(raw: unknown): number | undefined {
    if (raw === undefined || raw === null) return undefined;
    const n = typeof raw === 'number' ? raw : Number(String(raw).replace(/[^\d.+-]/g, ''));
    return Number.isFinite(n) ? n : undefined;
  }

  // ───────── Charts ─────────
  private safeChart(fn: () => void): void {
    try {
      fn();
    } catch (e) {
      console.warn('Chart render failed:', e);
    }
  }

  private renderAll(p: ProductResponse): void {
    if (!this.viewReady) return;
    this.destroyCharts();
    this.safeChart(() => this.renderLineChart(p));
    this.safeChart(() => this.renderChannelDoughnut(p));
    this.safeChart(() => this.renderPromoDoughnut(p));
    this.safeChart(() => this.renderMonthlyBar(p));
    this.safeChart(() => this.renderSavingsBar(p));
    this.safeChart(() => this.renderPolar(p));
    this.safeChart(() => this.renderDistribution(p));
    this.safeChart(() => this.renderYoyBar(p));
    this.safeChart(() => this.renderDeltaBar(p));
    this.safeChart(() => this.renderCumulativeSavings(p));
    this.safeChart(() => this.renderPromoDensity(p));
  }

  private destroyCharts(): void {
    for (const c of this.charts) c.destroy();
    this.charts = [];
  }

  private channelSeries(entries: PriceEntry[]): { x: number; y: number }[] {
    return entries
      .map((e) => ({ x: new Date(e.start_date).getTime(), y: Number(e.price) }))
      .filter((d) => Number.isFinite(d.x) && Number.isFinite(d.y))
      .sort((a, b) => a.x - b.x);
  }

  private renderLineChart(p: ProductResponse): void {
    const canvas = this.lineChart?.nativeElement;
    if (!canvas) return;

    const timelineSet = new Set<number>();
    for (const ch of ['normal', 'discount', 'clubcard'] as Channel[]) {
      for (const e of p.price_history?.[ch] ?? []) {
        const t = new Date(e.start_date).getTime();
        if (Number.isFinite(t)) timelineSet.add(t);
      }
    }
    const timeline = Array.from(timelineSet).sort((a, b) => a - b);
    if (!timeline.length) return;
    const labels = timeline.map((t) => new Date(t).toLocaleDateString());

    const datasets = (['normal', 'discount', 'clubcard'] as Channel[])
      .map((channel) => {
        const entries = p.price_history?.[channel] ?? [];
        if (!entries.length) return null;
        const series = this.channelSeries(entries);
        const byTs = new Map(series.map((d) => [d.x, d.y]));
        const data = timeline.map((t) => (byTs.has(t) ? (byTs.get(t) as number) : null));
        const col = CHANNEL_COLOURS[channel];
        return {
          label: channel.charAt(0).toUpperCase() + channel.slice(1),
          data,
          borderColor: col.border,
          backgroundColor: col.bg,
          fill: channel === 'normal',
          tension: 0.3,
          pointRadius: 2,
          pointHoverRadius: 5,
          borderWidth: 2,
          spanGaps: true,
        };
      })
      .filter((d): d is NonNullable<typeof d> => d !== null);

    if (!datasets.length) return;

    this.charts.push(
      new Chart(canvas, {
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
                label: (ctx) =>
                  ctx.parsed.y === null
                    ? `${ctx.dataset.label}: —`
                    : `${ctx.dataset.label}: ${Number(ctx.parsed.y).toFixed(2)} Ft`,
              },
            },
          },
        },
      }),
    );
  }

  private renderChannelDoughnut(p: ProductResponse): void {
    const canvas = this.channelDoughnut?.nativeElement;
    if (!canvas) return;
    const normal = p.price_history?.normal?.length ?? 0;
    const discount = p.price_history?.discount?.length ?? 0;
    const clubcard = p.price_history?.clubcard?.length ?? 0;
    if (!(normal + discount + clubcard)) return;

    this.charts.push(
      new Chart(canvas, {
        type: 'doughnut',
        data: {
          labels: ['Normal', 'Discount', 'Clubcard'],
          datasets: [
            {
              data: [normal, discount, clubcard],
              backgroundColor: [
                CHANNEL_COLOURS.normal.border,
                CHANNEL_COLOURS.discount.border,
                CHANNEL_COLOURS.clubcard.border,
              ],
              borderWidth: 0,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: '65%',
          plugins: { legend: { position: 'bottom' } },
        },
      }),
    );
  }

  private renderPromoDoughnut(p: ProductResponse): void {
    const canvas = this.promoDoughnut?.nativeElement;
    if (!canvas) return;
    const all = this.allEntries(p);
    const promo = all.filter((e) => !!e.promo_id || !!e.promo_desc).length;
    const regular = all.length - promo;
    if (!all.length) return;

    this.charts.push(
      new Chart(canvas, {
        type: 'doughnut',
        data: {
          labels: ['Promotional', 'Regular'],
          datasets: [
            {
              data: [promo, regular],
              backgroundColor: ['rgb(220, 38, 38)', 'rgb(148, 163, 184)'],
              borderWidth: 0,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: '65%',
          plugins: { legend: { position: 'bottom' } },
        },
      }),
    );
  }

  private renderMonthlyBar(p: ProductResponse): void {
    const canvas = this.monthlyBar?.nativeElement;
    if (!canvas) return;

    const byMonth = new Map<string, number[]>();
    for (const e of this.allEntries(p)) {
      const d = new Date(e.start_date);
      if (!Number.isFinite(d.getTime())) continue;
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
      const arr = byMonth.get(key) ?? [];
      arr.push(e.price);
      byMonth.set(key, arr);
    }
    if (!byMonth.size) return;

    const labels = Array.from(byMonth.keys()).sort();
    const avgs = labels.map((k) => {
      const arr = byMonth.get(k)!;
      return arr.reduce((a, b) => a + b, 0) / arr.length;
    });

    this.charts.push(
      new Chart(canvas, {
        type: 'bar',
        data: {
          labels,
          datasets: [
            {
              label: 'Avg price',
              data: avgs,
              backgroundColor: CHANNEL_COLOURS.normal.bg,
              borderColor: CHANNEL_COLOURS.normal.border,
              borderWidth: 1,
              borderRadius: 4,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: { grid: { display: false } },
            y: { beginAtZero: false, ticks: { callback: (v) => `${v} Ft` } },
          },
          plugins: { legend: { display: false } },
        },
      }),
    );
  }

  private renderSavingsBar(p: ProductResponse): void {
    const canvas = this.savingsBar?.nativeElement;
    if (!canvas) return;

    const normal = p.price_history?.normal ?? [];
    const clubcard = p.price_history?.clubcard ?? [];
    if (!normal.length || !clubcard.length) return;

    const clubSeries = this.channelSeries(clubcard);
    const normSeries = this.channelSeries(normal);
    if (!clubSeries.length || !normSeries.length) return;

    const labels: string[] = [];
    const values: number[] = [];
    for (const cc of clubSeries) {
      const closest = normSeries.reduce((best, cur) =>
        Math.abs(cur.x - cc.x) < Math.abs(best.x - cc.x) ? cur : best,
      );
      if (closest.y > 0 && cc.y < closest.y) {
        labels.push(new Date(cc.x).toLocaleDateString());
        values.push(((closest.y - cc.y) / closest.y) * 100);
      }
    }
    if (!values.length) return;

    this.charts.push(
      new Chart(canvas, {
        type: 'bar',
        data: {
          labels,
          datasets: [
            {
              label: 'Clubcard savings %',
              data: values,
              backgroundColor: CHANNEL_COLOURS.clubcard.bg,
              borderColor: CHANNEL_COLOURS.clubcard.border,
              borderWidth: 1,
              borderRadius: 4,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } },
            y: { beginAtZero: true, ticks: { callback: (v) => `${v}%` } },
          },
          plugins: { legend: { display: false } },
        },
      }),
    );
  }

  private renderPolar(p: ProductResponse): void {
    const canvas = this.polarChart?.nativeElement;
    if (!canvas) return;

    const channels: Channel[] = ['normal', 'discount', 'clubcard'];
    const labels: string[] = [];
    const data: number[] = [];
    const colours: string[] = [];

    for (const ch of channels) {
      const entries = p.price_history?.[ch] ?? [];
      const prices = entries.map((e) => e.price).filter((n) => Number.isFinite(n));
      if (!prices.length) continue;
      const avg = prices.reduce((a, b) => a + b, 0) / prices.length;
      labels.push(ch.charAt(0).toUpperCase() + ch.slice(1));
      data.push(Number(avg.toFixed(2)));
      colours.push(CHANNEL_COLOURS[ch].bg.replace('0.15', '0.5').replace('0.20', '0.55'));
    }
    if (!data.length) return;

    this.charts.push(
      new Chart(canvas, {
        type: 'polarArea',
        data: {
          labels,
          datasets: [{ data, backgroundColor: colours, borderWidth: 0 }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: { r: { ticks: { callback: (v) => `${v} Ft` } } },
          plugins: { legend: { position: 'bottom' } },
        },
      }),
    );
  }

  private renderDistribution(p: ProductResponse): void {
    const canvas = this.distributionBar?.nativeElement;
    if (!canvas) return;

    const prices = this.allEntries(p).map((e) => e.price).filter((n) => Number.isFinite(n));
    if (prices.length < 2) return;

    const min = Math.min(...prices);
    const max = Math.max(...prices);
    if (max === min) return;

    const bucketCount = 8;
    const step = (max - min) / bucketCount;
    const buckets = new Array<number>(bucketCount).fill(0);
    for (const v of prices) {
      const idx = Math.min(bucketCount - 1, Math.floor((v - min) / step));
      buckets[idx]++;
    }
    const labels = buckets.map((_, i) => {
      const lo = min + i * step;
      const hi = lo + step;
      return `${lo.toFixed(2)}–${hi.toFixed(2)} Ft`;
    });

    this.charts.push(
      new Chart(canvas, {
        type: 'bar',
        data: {
          labels,
          datasets: [
            {
              label: 'Observations',
              data: buckets,
              backgroundColor: 'rgba(16, 185, 129, 0.25)',
              borderColor: 'rgb(16, 185, 129)',
              borderWidth: 1,
              borderRadius: 4,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: { grid: { display: false }, ticks: { autoSkip: false, maxRotation: 45, minRotation: 30 } },
            y: { beginAtZero: true, ticks: { precision: 0 } },
          },
          plugins: { legend: { display: false } },
        },
      }),
    );
  }

  // ───────── New charts ─────────

  private renderYoyBar(p: ProductResponse): void {
    const canvas = this.yoyBar?.nativeElement;
    if (!canvas) return;

    const byYear = new Map<string, { minVal: number; sum: number; maxVal: number; count: number }>();
    for (const e of this.allEntries(p)) {
      const d = new Date(e.start_date);
      if (!Number.isFinite(d.getTime()) || !Number.isFinite(e.price)) continue;
      const yr = String(d.getFullYear());
      const cur = byYear.get(yr) ?? { minVal: Infinity, sum: 0, maxVal: -Infinity, count: 0 };
      byYear.set(yr, {
        minVal: Math.min(cur.minVal, e.price),
        sum: cur.sum + e.price,
        maxVal: Math.max(cur.maxVal, e.price),
        count: cur.count + 1,
      });
    }
    if (byYear.size < 1) return;

    const labels = Array.from(byYear.keys()).sort();
    const minData = labels.map((yr) => Number(byYear.get(yr)!.minVal.toFixed(2)));
    const avgData = labels.map((yr) => {
      const v = byYear.get(yr)!;
      return Number((v.sum / v.count).toFixed(2));
    });
    const maxData = labels.map((yr) => Number(byYear.get(yr)!.maxVal.toFixed(2)));

    this.charts.push(
      new Chart(canvas, {
        type: 'bar',
        data: {
          labels,
          datasets: [
            { label: 'Min', data: minData, backgroundColor: 'rgba(16, 185, 129, 0.6)', borderColor: 'rgb(16, 185, 129)', borderWidth: 1, borderRadius: 4 },
            { label: 'Avg', data: avgData, backgroundColor: 'rgba(59, 130, 246, 0.6)', borderColor: 'rgb(59, 130, 246)', borderWidth: 1, borderRadius: 4 },
            { label: 'Max', data: maxData, backgroundColor: 'rgba(239, 68, 68, 0.6)', borderColor: 'rgb(239, 68, 68)', borderWidth: 1, borderRadius: 4 },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: { grid: { display: false } },
            y: { beginAtZero: false, ticks: { callback: (v) => `${v} Ft` } },
          },
          plugins: { legend: { position: 'bottom' } },
        },
      }),
    );
  }

  private renderDeltaBar(p: ProductResponse): void {
    const canvas = this.deltaBar?.nativeElement;
    if (!canvas) return;

    const byMonth = new Map<string, number[]>();
    for (const e of p.price_history.normal ?? []) {
      const d = new Date(e.start_date);
      if (!Number.isFinite(d.getTime()) || !Number.isFinite(e.price)) continue;
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
      const arr = byMonth.get(key) ?? [];
      arr.push(e.price);
      byMonth.set(key, arr);
    }
    if (byMonth.size < 2) return;

    const months = Array.from(byMonth.keys()).sort();
    const avgs = months.map((m) => {
      const arr = byMonth.get(m)!;
      return arr.reduce((a, b) => a + b, 0) / arr.length;
    });

    const labels: string[] = [];
    const deltas: number[] = [];
    const colors: string[] = [];

    for (let i = 1; i < months.length; i++) {
      const delta = avgs[i] - avgs[i - 1];
      labels.push(months[i]);
      deltas.push(Number(delta.toFixed(4)));
      colors.push(delta >= 0 ? 'rgba(239, 68, 68, 0.7)' : 'rgba(16, 185, 129, 0.7)');
    }
    if (!deltas.length) return;

    this.charts.push(
      new Chart(canvas, {
        type: 'bar',
        data: {
          labels,
          datasets: [
            {
              label: 'Price change vs previous month',
              data: deltas,
              backgroundColor: colors,
              borderColor: colors.map((c) => c.replace('0.7', '1')),
              borderWidth: 1,
              borderRadius: 4,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: { grid: { display: false }, ticks: { maxTicksLimit: 12, autoSkip: true } },
            y: { ticks: { callback: (v) => `${Number(v).toFixed(2)} Ft` } },
          },
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: (ctx) => {
                  const v = Number(ctx.parsed.y);
                  return v >= 0 ? `+${v.toFixed(2)} Ft increase` : `-${Math.abs(v).toFixed(2)} Ft decrease`;
                },
              },
            },
          },
        },
      }),
    );
  }

  private renderCumulativeSavings(p: ProductResponse): void {
    const canvas = this.cumulativeSavings?.nativeElement;
    if (!canvas) return;

    const normSeries = this.channelSeries(p.price_history.normal ?? []);
    const clubSeries = this.channelSeries(p.price_history.clubcard ?? []);
    if (!normSeries.length || !clubSeries.length) return;

    const timelineSet = new Set<number>();
    for (const d of [...normSeries, ...clubSeries]) timelineSet.add(d.x);
    const timeline = Array.from(timelineSet).sort((a, b) => a - b);

    const normByTs = new Map(normSeries.map((d) => [d.x, d.y]));
    const clubByTs = new Map(clubSeries.map((d) => [d.x, d.y]));

    const labels: string[] = [];
    const cumulative: number[] = [];
    let total = 0;

    for (const t of timeline) {
      const norm = normByTs.get(t);
      const club = clubByTs.get(t);
      if (norm !== undefined && club !== undefined && norm > club) {
        total += norm - club;
      }
      labels.push(new Date(t).toLocaleDateString());
      cumulative.push(Number(total.toFixed(2)));
    }

    if (!cumulative.some((v) => v > 0)) return;

    this.charts.push(
      new Chart(canvas, {
        type: 'line',
        data: {
          labels,
          datasets: [
            {
              label: 'Cumulative Clubcard savings',
              data: cumulative,
              borderColor: CHANNEL_COLOURS.clubcard.border,
              backgroundColor: CHANNEL_COLOURS.clubcard.bg,
              fill: true,
              tension: 0.4,
              pointRadius: 1,
              pointHoverRadius: 4,
              borderWidth: 2,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: { grid: { display: false }, ticks: { maxTicksLimit: 10, autoSkip: true } },
            y: { beginAtZero: true, ticks: { callback: (v) => `${v} Ft` } },
          },
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: { label: (ctx) => `Total saved: ${Number(ctx.parsed.y).toFixed(2)} Ft` },
            },
          },
        },
      }),
    );
  }

  private renderPromoDensity(p: ProductResponse): void {
    const canvas = this.promoDensityBar?.nativeElement;
    if (!canvas) return;

    const byMonth = new Map<string, { total: number; promo: number }>();
    for (const e of this.allEntries(p)) {
      const d = new Date(e.start_date);
      if (!Number.isFinite(d.getTime())) continue;
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
      const cur = byMonth.get(key) ?? { total: 0, promo: 0 };
      cur.total++;
      if (e.promo_id || e.promo_desc) cur.promo++;
      byMonth.set(key, cur);
    }
    if (!byMonth.size) return;

    const labels = Array.from(byMonth.keys()).sort();
    const pctData = labels.map((m) => {
      const v = byMonth.get(m)!;
      return v.total > 0 ? Number(((v.promo / v.total) * 100).toFixed(1)) : 0;
    });

    if (!pctData.some((v) => v > 0)) return;

    this.charts.push(
      new Chart(canvas, {
        type: 'bar',
        data: {
          labels,
          datasets: [
            {
              label: 'Promo %',
              data: pctData,
              backgroundColor: 'rgba(220, 38, 38, 0.35)',
              borderColor: 'rgb(220, 38, 38)',
              borderWidth: 1,
              borderRadius: 4,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: { grid: { display: false }, ticks: { maxTicksLimit: 12, autoSkip: true } },
            y: { beginAtZero: true, max: 100, ticks: { callback: (v) => `${v}%` } },
          },
          plugins: { legend: { display: false } },
        },
      }),
    );
  }
}
