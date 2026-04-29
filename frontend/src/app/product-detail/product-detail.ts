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
import { combineLatest } from 'rxjs';
import {
  ProductDetail as ProductDetailModel,
  ProductHistory,
  ProductStats,
  ProductsService,
} from '../services/products.service';
import { AuthService } from '../services/auth.service';
import { AlertDirection, AlertsService } from '../services/alerts.service';

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
  alertThreshold: number | null = null;
  alertDirection: AlertDirection = 'below';
  readonly alertSaving = signal(false);
  readonly alertMessage = signal('');

  private chart?: Chart;

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
      stats: this.products.stats(tpnc),
      history: this.products.history(tpnc),
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
          y: { beginAtZero: false, ticks: { callback: (v) => `£${v}` } },
        },
        plugins: { legend: { display: false } },
      },
    };

    this.chart = new Chart(canvas, config);
  }

  saveAlert(): void {
    const threshold = this.alertThreshold;
    const tpnc = this.tpnc();
    if (!tpnc || threshold === null || Number.isNaN(threshold)) {
      this.alertMessage.set('Enter a numeric threshold.');
      return;
    }
    this.alertSaving.set(true);
    this.alertMessage.set('');
    this.alertsApi.create({ tpnc, threshold, direction: this.alertDirection }).subscribe({
      next: () => {
        this.alertMessage.set('Alert saved.');
        this.alertSaving.set(false);
        this.alertThreshold = null;
      },
      error: (err) => {
        this.alertMessage.set(err?.error?.error || 'Failed to save alert.');
        this.alertSaving.set(false);
      },
    });
  }

  ngOnDestroy(): void {
    this.chart?.destroy();
  }
}
