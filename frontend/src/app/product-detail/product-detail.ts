import {
  AfterViewInit,
  ChangeDetectorRef,
  Component,
  ElementRef,
  OnDestroy,
  ViewChild,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule, Location } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { TranslationService } from '../services/translation.service';
import { TranslatePipe } from '../shared/translate.pipe';
import { HexIcon }    from '../shared/hex-icon/hex-icon';
import { HexKpi }     from '../shared/hex-kpi/hex-kpi';
import { SecLabel }   from '../shared/sec-label/sec-label';
import {
  ArcElement,
  BarController,
  BarElement,
  CategoryScale,
  Chart,
  ChartConfiguration,
  DoughnutController,
  Filler,
  Legend,
  LineController,
  LineElement,
  LinearScale,
  PointElement,
  TimeScale,
  Tooltip,
} from 'chart.js';
import { combineLatest, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import {
  PriceEntry,
  ProductDetail as ProductDetailModel,
  ProductHistory,
  ProductResponse,
  ProductStats,
  ProductsService,
} from '../services/products.service';
import { AuthService } from '../services/auth.service';
import { AlertType, AlertsService, CreateAlertRequest } from '../services/alerts.service';

Chart.register(
  LineController,
  BarController,
  DoughnutController,
  LineElement,
  BarElement,
  ArcElement,
  PointElement,
  LinearScale,
  TimeScale,
  CategoryScale,
  Tooltip,
  Legend,
  Filler,
);

type Channel = 'normal' | 'discount' | 'clubcard';

const CHANNEL_COLOURS: Record<Channel, { border: string; bg: string }> = {
  normal:   { border: 'rgb(59, 130, 246)',  bg: 'rgba(59, 130, 246, 0.15)'  },
  discount: { border: 'rgb(249, 115, 22)',  bg: 'rgba(249, 115, 22, 0.15)'  },
  clubcard: { border: 'rgb(234, 179, 8)',   bg: 'rgba(234, 179, 8, 0.20)'   },
};

const MONTH_NAMES = [
  'January','February','March','April','May','June',
  'July','August','September','October','November','December',
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
  selector: 'app-product-detail',
  imports: [CommonModule, FormsModule, HexIcon, HexKpi, SecLabel, TranslatePipe],
  templateUrl: './product-detail.html',
  styleUrl: './product-detail.scss',
})
export class ProductDetail implements AfterViewInit, OnDestroy {
  @ViewChild('chartCanvas') chartCanvas?: ElementRef<HTMLCanvasElement>;
  // Analytics chart canvases
  @ViewChild('multiLineChart')  multiLineChart?:  ElementRef<HTMLCanvasElement>;
  @ViewChild('promoDoughnut')   promoDoughnut?:   ElementRef<HTMLCanvasElement>;
  @ViewChild('monthlyBar')      monthlyBar?:      ElementRef<HTMLCanvasElement>;
  @ViewChild('savingsBar')      savingsBar?:      ElementRef<HTMLCanvasElement>;
  @ViewChild('distributionBar') distributionBar?: ElementRef<HTMLCanvasElement>;
  @ViewChild('yoyBar')          yoyBar?:          ElementRef<HTMLCanvasElement>;
  @ViewChild('deltaBar')        deltaBar?:        ElementRef<HTMLCanvasElement>;

  readonly tl = inject(TranslationService);

  private route = inject(ActivatedRoute);
  private location = inject(Location);
  private products = inject(ProductsService);
  private alertsApi = inject(AlertsService);
  private cdr = inject(ChangeDetectorRef);
  public auth = inject(AuthService);

  readonly tpnc = signal<string>('');
  readonly product = signal<ProductDetailModel | null>(null);
  readonly stats = signal<ProductStats | null>(null);
  readonly history = signal<ProductHistory | null>(null);
  readonly loading = signal(true);
  readonly error = signal('');

  // Analytics signals
  readonly kpi = signal<KpiAgg>({ entryCount: 0, promoCount: 0 });
  readonly insights = signal<string[]>([]);

  // Alert form state.
  alertType: AlertType = 'TARGET_PRICE';
  alertTargetPrice: number | null = null;
  alertDropPercentage: number | null = null;
  readonly alertSaving = signal(false);
  readonly alertMessage = signal('');

  private chart?: Chart;
  private analyticsCharts: Chart[] = [];

  chartRange = signal<7 | 30 | 90>(this._initChartRange());

  private _initChartRange(): 7 | 30 | 90 {
    const cookie = document.cookie.match(/(?:^|; )tpt_chart_range=(\d+)/);
    const v = cookie ? parseInt(cookie[1], 10) : 30;
    return v === 7 ? 7 : v === 90 ? 90 : 30;
  }

  /** Current effective price for use in alert form validation. */
  get currentPrice(): number | null {
    const s = this.stats();
    return s?.current ?? null;
  }

  /** Buy signal derived from current vs historical avg. */
  readonly buySignal = computed(() => {
    const s = this.stats();
    if (!s?.current || !s?.avg) return null;
    return s.current <= s.avg ? 'good' : 'above';
  });

  /** Trend pct from first history point to last. */
  readonly trendPct = computed(() => {
    const h = this.history();
    if (!h?.points?.length || h.points.length < 2) return null;
    const first = h.points[0].price;
    const last  = h.points[h.points.length - 1].price;
    return Math.round(((last - first) / first) * 1000) / 10;
  });

  /** First letter of category for the hex icon. */
  readonly categoryLetter = computed(() => {
    const p = this.product();
    const cat = p?.category || p?.name || '?';
    return cat.charAt(0).toUpperCase();
  });

  /** Navigate back to the previously visited page (browser back semantics). */
  goBack(): void {
    this.location.back();
  }

  /** Formatted price points sliced by range for chart redraw. */
  setRange(range: 7 | 30 | 90): void {
    this.chartRange.set(range);
    document.cookie = `tpt_chart_range=${range}; path=/; max-age=${365 * 86400}; SameSite=Lax`;
    const h = this.history();
    if (!h) return;
    const sliced = range === 90 ? h : { ...h, points: h.points.slice(-range) };
    queueMicrotask(() => this.renderChart(sliced));
  }

  ngAfterViewInit(): void {
    this.route.paramMap.subscribe((params) => {
      const tpnc = params.get('tpnc') || '';
      this.tpnc.set(tpnc);
      if (tpnc) this.load(tpnc);
    });
  }

  private load(tpnc: string): void {
    this.loading.set(true);
    this.error.set('');
    combineLatest({
      product: this.products.get(tpnc),
      stats: this.products.stats(tpnc).pipe(catchError(() => of(null as ProductStats | null))),
      history: this.products.history(tpnc).pipe(catchError(() => of(null as ProductHistory | null))),
    }).subscribe({
      next: ({ product, stats, history }) => {
        this.product.set(product);
        this.stats.set(stats);
        this.history.set(history);
        this.loading.set(false);
        const range = this.chartRange();
        const sliced = history && range < 90 ? { ...history, points: history.points.slice(-range) } : history;
        // detectChanges forces Angular to render @if(product()) block so the canvas is in the DOM
        this.cdr.detectChanges();
        setTimeout(() => this.renderChart(sliced), 0);
        // Also load full product data for analytics charts
        this.products.getRaw(tpnc).pipe(catchError(() => of(null))).subscribe((raw) => {
          if (raw) {
            const kpi = this.computeKpis(raw);
            this.kpi.set(kpi);
            this.insights.set(this.computeInsights(raw, kpi));
            this.cdr.detectChanges();
            setTimeout(() => this.renderAnalytics(raw), 0);
          }
        });
      },
      error: (err) => {
        this.error.set(err?.error?.error || 'Failed to load product.');
        this.loading.set(false);
      },
    });
  }

  private renderChart(history: ProductHistory | null): void {
    const canvas = this.chartCanvas?.nativeElement;
    if (!canvas || !history?.points?.length) return;

    this.chart?.destroy();

    const labels = history.points.map((p) => new Date(p.timestamp).toLocaleDateString());
    const data = history.points.map((p) => p.price);

    const config: ChartConfiguration<'line'> = {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'Price',
            data,
            borderColor: 'rgb(59, 130, 246)',
            backgroundColor: 'rgba(59, 130, 246, 0.15)',
            fill: true,
            tension: 0.25,
            pointRadius: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { grid: { display: false } },
          y: { beginAtZero: false, ticks: { callback: (v) => `${v} Ft` } },
        },
        plugins: { legend: { display: false } },
      },
    };

    this.chart = new Chart(canvas, config);
  }

  saveAlert(): void {
    const tpnc = this.tpnc();
    if (!tpnc) return;

    this.alertMessage.set('');

    let req: CreateAlertRequest;

    if (this.alertType === 'TARGET_PRICE') {
      const target = this.alertTargetPrice;
      if (target === null || Number.isNaN(target) || target <= 0) {
        this.alertMessage.set('Enter a valid target price greater than 0.');
        return;
      }
      if (this.currentPrice !== null && target >= this.currentPrice) {
        this.alertMessage.set('Target price must be below the current price.');
        return;
      }
      req = { productId: tpnc, alertType: 'TARGET_PRICE', targetPrice: target };
    } else {
      const pct = this.alertDropPercentage;
      if (pct === null || Number.isNaN(pct) || pct <= 0 || pct > 100) {
        this.alertMessage.set('Enter a percentage between 1 and 100.');
        return;
      }
      const basePrice = this.currentPrice;
      if (basePrice === null || basePrice <= 0) {
        this.alertMessage.set('Current price is unavailable — cannot create percentage alert.');
        return;
      }
      req = { productId: tpnc, alertType: 'PERCENTAGE_DROP', dropPercentage: pct, basePriceAtCreation: basePrice };
    }

    this.alertSaving.set(true);
    this.alertsApi.create(req).subscribe({
      next: () => {
        this.alertMessage.set('Alert saved!');
        this.alertSaving.set(false);
        this.alertTargetPrice = null;
        this.alertDropPercentage = null;
      },
      error: (err) => {
        this.alertSaving.set(false);
        if (err?.status === 401 || err?.status === 403) {
          this.alertMessage.set('You must be logged in to set alerts. Please log in and try again.');
        } else {
          const detail = err?.error?.detail;
          this.alertMessage.set(detail || err?.error?.error || 'Failed to save alert.');
        }
      },
    });
  }

  ngOnDestroy(): void {
    this.chart?.destroy();
    for (const c of this.analyticsCharts) c.destroy();
    this.analyticsCharts = [];
  }

  // ─── Analytics helpers ──────────────────────────────────────────────

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

  buySignalLabel(kpi: KpiAgg): string {
    if (kpi.current === undefined || kpi.avg === undefined) return '—';
    const vsAvg = ((kpi.current - kpi.avg) / kpi.avg) * 100;
    if (kpi.current === kpi.min) return '🔥 All-time low!';
    if (vsAvg < -8) return '✅ Below average';
    if (vsAvg > 8) return '⚠️ Above average';
    return '➡️ Near average';
  }

  private computeKpis(p: ProductResponse): KpiAgg {
    const all = this.allEntries(p);
    if (!all.length) return { entryCount: 0, promoCount: 0 };

    const prices = all.map((e) => e.price).filter((n): n is number => Number.isFinite(n));
    const clubcardPrices = (p.price_history.clubcard ?? []).map((e) => e.price).filter((n): n is number => Number.isFinite(n));
    const min = prices.length ? Math.min(...prices) : undefined;
    const max = prices.length ? Math.max(...prices) : undefined;
    const avg = prices.length ? prices.reduce((a, b) => a + b, 0) / prices.length : undefined;
    const current = this.parseNumeric(p.last_scraped_price);
    const clubcardMin = clubcardPrices.length ? Math.min(...clubcardPrices) : undefined;
    const savingsPct = max !== undefined && clubcardMin !== undefined && max > 0
      ? ((max - clubcardMin) / max) * 100 : undefined;
    const promoCount = all.filter((e) => !!e.promo_id || !!e.promo_desc).length;

    const dates = all.map((e) => new Date(e.start_date).getTime()).filter((n) => Number.isFinite(n));
    const firstSeen = dates.length ? new Date(Math.min(...dates)) : undefined;
    const lastSeen  = dates.length ? new Date(Math.max(...dates)) : undefined;

    const stdDev = avg !== undefined && prices.length >= 2
      ? Math.sqrt(prices.reduce((a, b) => a + Math.pow(b - avg, 2), 0) / prices.length) : undefined;
    const volatility = avg && stdDev !== undefined ? (stdDev / avg) * 100 : undefined;

    const normalEntries = (p.price_history.normal ?? [])
      .filter((e) => Number.isFinite(new Date(e.start_date).getTime()))
      .sort((a, b) => new Date(a.start_date).getTime() - new Date(b.start_date).getTime());
    const now = Date.now();
    const DAY = 24 * 3600 * 1000;
    const recent = normalEntries.filter((e) => now - new Date(e.start_date).getTime() < 30 * DAY);
    const prior  = normalEntries.filter((e) => { const age = now - new Date(e.start_date).getTime(); return age >= 30 * DAY && age < 60 * DAY; });
    const recentAvg = recent.length ? recent.reduce((a, b) => a + b.price, 0) / recent.length : undefined;
    const priorAvg  = prior.length  ? prior.reduce((a, b) => a + b.price, 0) / prior.length   : undefined;
    const trendPct = recentAvg !== undefined && priorAvg !== undefined && priorAvg > 0
      ? ((recentAvg - priorAvg) / priorAvg) * 100 : undefined;

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
      if (mAvg < bestMonthAvg) { bestMonthAvg = mAvg; bestMonth = MONTH_NAMES[m]; }
    }

    const daysTracked = firstSeen ? Math.round((Date.now() - firstSeen.getTime()) / DAY) : undefined;
    const promoFreqPct = all.length > 0 ? (promoCount / all.length) * 100 : undefined;

    let priceChanges = 0;
    for (let i = 1; i < normalEntries.length; i++) {
      if (normalEntries[i].price !== normalEntries[i - 1].price) priceChanges++;
    }

    const normSeries = this.channelSeries(p.price_history.normal ?? []);
    const clubSeries = this.channelSeries(p.price_history.clubcard ?? []);
    let clubcardTotalSavings = 0;
    if (normSeries.length && clubSeries.length) {
      for (const cc of clubSeries) {
        const closest = normSeries.reduce((best, cur) =>
          Math.abs(cur.x - cc.x) < Math.abs(best.x - cc.x) ? cur : best);
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
      out.push('This is the all-time lowest recorded price — a great time to buy.');
    } else if (kpi.current !== undefined && kpi.avg !== undefined && kpi.avg > 0) {
      const vsAvg = ((kpi.current - kpi.avg) / kpi.avg) * 100;
      if (vsAvg < -8) out.push(`Current price is ${Math.abs(vsAvg).toFixed(1)}% below the historical average — currently a great deal.`);
      else if (vsAvg > 8) out.push(`Current price is ${vsAvg.toFixed(1)}% above the historical average — consider waiting for a discount.`);
    }
    if (kpi.trendPct !== undefined) {
      if (kpi.trendPct > 5) out.push(`Price is up ${kpi.trendPct.toFixed(1)}% over the last 30 days vs the prior period.`);
      else if (kpi.trendPct < -5) out.push(`Price has fallen ${Math.abs(kpi.trendPct).toFixed(1)}% over the last 30 days — downward momentum.`);
      else out.push(`Price has been stable over the last 30 days (${kpi.trendPct >= 0 ? '+' : ''}${kpi.trendPct.toFixed(1)}%).`);
    }
    if (kpi.bestMonth) out.push(`Historically, ${kpi.bestMonth} has the lowest average prices.`);
    if (kpi.savingsPct !== undefined && kpi.savingsPct > 0)
      out.push(`Clubcard delivers up to ${kpi.savingsPct.toFixed(1)}% off vs. the highest normal price on record.`);
    if (kpi.promoFreqPct !== undefined && kpi.promoFreqPct > 25)
      out.push(`Promotions occur in ${kpi.promoFreqPct.toFixed(0)}% of price records — worth keeping an alert active.`);
    if (kpi.volatility !== undefined && kpi.volatility > 15)
      out.push(`Price is highly volatile (${kpi.volatility.toFixed(1)}% CV) — set an alert to catch the next dip.`);
    return out;
  }

  private allEntries(p: ProductResponse): PriceEntry[] {
    const { normal = [], discount = [], clubcard = [] } = p.price_history ?? {};
    return [...normal, ...discount, ...clubcard];
  }

  private parseNumeric(raw: unknown): number | undefined {
    if (raw === undefined || raw === null) return undefined;
    const n = typeof raw === 'number' ? raw : Number(String(raw).replace(/[^\d.+-]/g, ''));
    return Number.isFinite(n) ? n : undefined;
  }

  private channelSeries(entries: PriceEntry[]): { x: number; y: number }[] {
    return entries.map((e) => ({ x: new Date(e.start_date).getTime(), y: Number(e.price) }))
      .filter((d) => Number.isFinite(d.x) && Number.isFinite(d.y))
      .sort((a, b) => a.x - b.x);
  }

  private renderAnalytics(p: ProductResponse): void {
    for (const c of this.analyticsCharts) c.destroy();
    this.analyticsCharts = [];
    const safe = (fn: () => void) => { try { fn(); } catch (e) { console.warn('chart render failed', e); } };
    safe(() => this.renderMultiLineChart(p));
    safe(() => this.renderPromoDoughnut(p));
    safe(() => this.renderMonthlyBar(p));
    safe(() => this.renderSavingsBar(p));
    safe(() => this.renderDistribution(p));
    safe(() => this.renderYoyBar(p));
    safe(() => this.renderDeltaBar(p));
  }

  private renderMultiLineChart(p: ProductResponse): void {
    const canvas = this.multiLineChart?.nativeElement;
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
    const datasets = (['normal', 'discount', 'clubcard'] as Channel[]).map((ch) => {
      const entries = p.price_history?.[ch] ?? [];
      if (!entries.length) return null;
      const series = this.channelSeries(entries);
      const byTs = new Map(series.map((d) => [d.x, d.y]));
      const data = timeline.map((t) => byTs.has(t) ? (byTs.get(t) as number) : null);
      const col = CHANNEL_COLOURS[ch];
      return { label: ch.charAt(0).toUpperCase() + ch.slice(1), data, borderColor: col.border, backgroundColor: col.bg, fill: ch === 'normal', tension: 0.3, pointRadius: 2, borderWidth: 2, spanGaps: true };
    }).filter((d): d is NonNullable<typeof d> => d !== null);
    if (!datasets.length) return;
    this.analyticsCharts.push(new Chart(canvas, {
      type: 'line',
      data: { labels, datasets },
      options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
        scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 10, autoSkip: true } }, y: { beginAtZero: false, ticks: { callback: (v) => `${v} Ft` } } },
        plugins: { legend: { position: 'bottom' }, tooltip: { callbacks: { label: (ctx) => ctx.parsed.y === null ? `${ctx.dataset.label}: —` : `${ctx.dataset.label}: ${Number(ctx.parsed.y).toFixed(2)} Ft` } } } },
    }));
  }

  private renderPromoDoughnut(p: ProductResponse): void {
    const canvas = this.promoDoughnut?.nativeElement;
    if (!canvas) return;
    const all = this.allEntries(p);
    const promo = all.filter((e) => !!e.promo_id || !!e.promo_desc).length;
    if (!all.length) return;
    this.analyticsCharts.push(new Chart(canvas, {
      type: 'doughnut',
      data: { labels: ['Promotional', 'Regular'], datasets: [{ data: [promo, all.length - promo], backgroundColor: ['rgb(220, 38, 38)', 'rgb(148, 163, 184)'], borderWidth: 0 }] },
      options: { responsive: true, maintainAspectRatio: false, cutout: '65%', plugins: { legend: { position: 'bottom' } } },
    }));
  }

  private renderMonthlyBar(p: ProductResponse): void {
    const canvas = this.monthlyBar?.nativeElement;
    if (!canvas) return;
    const byMonth = new Map<string, number[]>();
    for (const e of this.allEntries(p)) {
      const d = new Date(e.start_date);
      if (!Number.isFinite(d.getTime())) continue;
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
      const arr = byMonth.get(key) ?? []; arr.push(e.price); byMonth.set(key, arr);
    }
    if (!byMonth.size) return;
    const labels = Array.from(byMonth.keys()).sort();
    const avgs = labels.map((k) => { const a = byMonth.get(k)!; return a.reduce((x, y) => x + y, 0) / a.length; });
    this.analyticsCharts.push(new Chart(canvas, {
      type: 'bar',
      data: { labels, datasets: [{ label: 'Avg price', data: avgs, backgroundColor: CHANNEL_COLOURS.normal.bg, borderColor: CHANNEL_COLOURS.normal.border, borderWidth: 1, borderRadius: 4 }] },
      options: { responsive: true, maintainAspectRatio: false, scales: { x: { grid: { display: false } }, y: { beginAtZero: false, ticks: { callback: (v) => `${v} Ft` } } }, plugins: { legend: { display: false } } },
    }));
  }

  private renderSavingsBar(p: ProductResponse): void {
    const canvas = this.savingsBar?.nativeElement;
    if (!canvas) return;
    const normSeries = this.channelSeries(p.price_history?.normal ?? []);
    const clubSeries = this.channelSeries(p.price_history?.clubcard ?? []);
    if (!normSeries.length || !clubSeries.length) return;
    const labels: string[] = []; const values: number[] = [];
    for (const cc of clubSeries) {
      const closest = normSeries.reduce((best, cur) => Math.abs(cur.x - cc.x) < Math.abs(best.x - cc.x) ? cur : best);
      if (closest.y > 0 && cc.y < closest.y) { labels.push(new Date(cc.x).toLocaleDateString()); values.push(((closest.y - cc.y) / closest.y) * 100); }
    }
    if (!values.length) return;
    this.analyticsCharts.push(new Chart(canvas, {
      type: 'bar',
      data: { labels, datasets: [{ label: 'Clubcard savings %', data: values, backgroundColor: CHANNEL_COLOURS.clubcard.bg, borderColor: CHANNEL_COLOURS.clubcard.border, borderWidth: 1, borderRadius: 4 }] },
      options: { responsive: true, maintainAspectRatio: false, scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } }, y: { beginAtZero: true, ticks: { callback: (v) => `${v}%` } } }, plugins: { legend: { display: false } } },
    }));
  }

  private renderDistribution(p: ProductResponse): void {
    const canvas = this.distributionBar?.nativeElement;
    if (!canvas) return;
    const prices = this.allEntries(p).map((e) => e.price).filter((n) => Number.isFinite(n));
    if (prices.length < 2) return;
    const min = Math.min(...prices); const max = Math.max(...prices);
    if (max === min) return;
    const N = 8; const step = (max - min) / N;
    const buckets = new Array<number>(N).fill(0);
    for (const v of prices) { const idx = Math.min(N - 1, Math.floor((v - min) / step)); buckets[idx]++; }
    const labels = buckets.map((_, i) => { const lo = min + i * step; return `${lo.toFixed(2)}–${(lo + step).toFixed(2)}`; });
    this.analyticsCharts.push(new Chart(canvas, {
      type: 'bar',
      data: { labels, datasets: [{ label: 'Observations', data: buckets, backgroundColor: 'rgba(16, 185, 129, 0.25)', borderColor: 'rgb(16, 185, 129)', borderWidth: 1, borderRadius: 4 }] },
      options: { responsive: true, maintainAspectRatio: false, scales: { x: { grid: { display: false }, ticks: { autoSkip: false, maxRotation: 45, minRotation: 30 } }, y: { beginAtZero: true, ticks: { precision: 0 } } }, plugins: { legend: { display: false } } },
    }));
  }

  private renderYoyBar(p: ProductResponse): void {
    const canvas = this.yoyBar?.nativeElement;
    if (!canvas) return;
    const byYear = new Map<string, { minVal: number; sum: number; maxVal: number; count: number }>();
    for (const e of this.allEntries(p)) {
      const d = new Date(e.start_date);
      if (!Number.isFinite(d.getTime()) || !Number.isFinite(e.price)) continue;
      const yr = String(d.getFullYear());
      const cur = byYear.get(yr) ?? { minVal: Infinity, sum: 0, maxVal: -Infinity, count: 0 };
      byYear.set(yr, { minVal: Math.min(cur.minVal, e.price), sum: cur.sum + e.price, maxVal: Math.max(cur.maxVal, e.price), count: cur.count + 1 });
    }
    if (byYear.size < 1) return;
    const labels = Array.from(byYear.keys()).sort();
    this.analyticsCharts.push(new Chart(canvas, {
      type: 'bar',
      data: { labels, datasets: [
        { label: 'Min', data: labels.map((yr) => +byYear.get(yr)!.minVal.toFixed(2)), backgroundColor: 'rgba(16, 185, 129, 0.6)', borderColor: 'rgb(16, 185, 129)', borderWidth: 1, borderRadius: 4 },
        { label: 'Avg', data: labels.map((yr) => { const v = byYear.get(yr)!; return +(v.sum / v.count).toFixed(2); }), backgroundColor: 'rgba(59, 130, 246, 0.6)', borderColor: 'rgb(59, 130, 246)', borderWidth: 1, borderRadius: 4 },
        { label: 'Max', data: labels.map((yr) => +byYear.get(yr)!.maxVal.toFixed(2)), backgroundColor: 'rgba(239, 68, 68, 0.6)', borderColor: 'rgb(239, 68, 68)', borderWidth: 1, borderRadius: 4 },
      ] },
      options: { responsive: true, maintainAspectRatio: false, scales: { x: { grid: { display: false } }, y: { beginAtZero: false, ticks: { callback: (v) => `${v} Ft` } } }, plugins: { legend: { position: 'bottom' } } },
    }));
  }

  private renderDeltaBar(p: ProductResponse): void {
    const canvas = this.deltaBar?.nativeElement;
    if (!canvas) return;
    const byMonth = new Map<string, number[]>();
    for (const e of p.price_history.normal ?? []) {
      const d = new Date(e.start_date);
      if (!Number.isFinite(d.getTime()) || !Number.isFinite(e.price)) continue;
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
      const arr = byMonth.get(key) ?? []; arr.push(e.price); byMonth.set(key, arr);
    }
    if (byMonth.size < 2) return;
    const months = Array.from(byMonth.keys()).sort();
    const avgs = months.map((m) => { const a = byMonth.get(m)!; return a.reduce((x, y) => x + y, 0) / a.length; });
    const labels: string[] = []; const deltas: number[] = []; const colors: string[] = [];
    for (let i = 1; i < months.length; i++) {
      const delta = avgs[i] - avgs[i - 1];
      labels.push(months[i]); deltas.push(+delta.toFixed(4));
      colors.push(delta >= 0 ? 'rgba(239, 68, 68, 0.7)' : 'rgba(16, 185, 129, 0.7)');
    }
    if (!deltas.length) return;
    this.analyticsCharts.push(new Chart(canvas, {
      type: 'bar',
      data: { labels, datasets: [{ label: 'MoM delta', data: deltas, backgroundColor: colors, borderColor: colors.map((c) => c.replace('0.7', '1')), borderWidth: 1, borderRadius: 4 }] },
      options: { responsive: true, maintainAspectRatio: false,
        scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 12, autoSkip: true } }, y: { ticks: { callback: (v) => `${Number(v).toFixed(2)} Ft` } } },
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => { const v = Number(ctx.parsed.y); return v >= 0 ? `+${v.toFixed(2)} Ft` : `-${Math.abs(v).toFixed(2)} Ft`; } } } } },
    }));
  }

  formatArrayOrString(value: any): string {
    if (!value) return '';
    if (Array.isArray(value)) return value.join(', ');
    return String(value);
  }
}