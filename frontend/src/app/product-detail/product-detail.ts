import {
  AfterViewInit,
  Component,
  ElementRef,
  OnDestroy,
  ViewChild,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import {
  Chart,
  ChartConfiguration,
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  TimeScale,
  Tooltip,
  Legend,
  Filler,
  CategoryScale,
} from 'chart.js';
import { combineLatest, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import {
  ProductDetail as ProductDetailModel,
  ProductHistory,
  ProductStats,
  ProductsService,
} from '../services/products.service';
import { AuthService } from '../services/auth.service';
import { AlertType, AlertsService, CreateAlertRequest } from '../services/alerts.service';

Chart.register(
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  TimeScale,
  CategoryScale,
  Tooltip,
  Legend,
  Filler,
);

@Component({
  selector: 'app-product-detail',
  imports: [CommonModule, FormsModule],
  templateUrl: './product-detail.html',
  styleUrl: './product-detail.scss',
})
export class ProductDetail implements AfterViewInit, OnDestroy {
  @ViewChild('chartCanvas') chartCanvas?: ElementRef<HTMLCanvasElement>;

  private route = inject(ActivatedRoute);
  private products = inject(ProductsService);
  private alertsApi = inject(AlertsService);
  public auth = inject(AuthService);

  readonly tpnc = signal<string>('');
  readonly product = signal<ProductDetailModel | null>(null);
  readonly stats = signal<ProductStats | null>(null);
  readonly history = signal<ProductHistory | null>(null);
  readonly loading = signal(true);
  readonly error = signal('');

  // Alert form state.
  alertType: AlertType = 'TARGET_PRICE';
  alertTargetPrice: number | null = null;
  alertDropPercentage: number | null = null;
  readonly alertSaving = signal(false);
  readonly alertMessage = signal('');

  private chart?: Chart;

  /** Current effective price for use in alert form validation. */
  get currentPrice(): number | null {
    const s = this.stats();
    return s?.current ?? null;
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
        queueMicrotask(() => this.renderChart(history));
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
        const detail = err?.error?.detail;
        this.alertMessage.set(detail || err?.error?.error || 'Failed to save alert.');
        this.alertSaving.set(false);
      },
    });
  }

  ngOnDestroy(): void {
    this.chart?.destroy();
  }

  formatArrayOrString(value: any): string {
    if (!value) return '';
    if (Array.isArray(value)) return value.join(', ');
    return String(value);
  }
}
