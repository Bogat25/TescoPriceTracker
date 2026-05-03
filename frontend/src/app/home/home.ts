import { Component, OnInit, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { catchError, of, forkJoin } from 'rxjs';
import { AppConfigService } from '../services/app-config.service';
import { PlatformStatsService, DiscountByWeekday } from '../services/platform-stats.service';
import { AlertsService, PriceAlert } from '../services/alerts.service';
import { ProductsService } from '../services/products.service';
import { AuthService } from '../services/auth.service';
import { TranslationService } from '../services/translation.service';
import { TranslatePipe } from '../shared/translate.pipe';
import { HexKpi }   from '../shared/hex-kpi/hex-kpi';
import { HexIcon }  from '../shared/hex-icon/hex-icon';
import { SecLabel } from '../shared/sec-label/sec-label';

@Component({
  selector: 'app-home',
  imports: [CommonModule, RouterLink, HexKpi, SecLabel, TranslatePipe],
  templateUrl: './home.html',
  styleUrl: './home.scss',
})
export class Home implements OnInit {
  private http = inject(HttpClient);
  private config = inject(AppConfigService);
  private statsService = inject(PlatformStatsService);
  private alertsService = inject(AlertsService);
  private productsService = inject(ProductsService);
  readonly auth = inject(AuthService);
  readonly tl   = inject(TranslationService);

  readonly healthOk = signal<boolean | null>(null);
  readonly productCount = signal<number | null>(null);
  readonly statsLoading = signal(true);

  readonly volatility  = signal<string>('');
  readonly trend30d    = signal<string>('');
  readonly bestWeekday = signal<string>('');
  readonly maxDiscount = signal<string>('');
  readonly buySignal   = signal<string>('');

  readonly recentAlerts   = signal<PriceAlert[]>([]);
  readonly alertsLoaded   = signal(false);
  readonly alertProductNames = signal<Map<string, string>>(new Map());
  readonly enabledAlertCount = computed(() => this.recentAlerts().filter(a => a.enabled).length);

  alertProductName(productId: string): string {
    return this.alertProductNames().get(productId) ?? productId;
  }

  ngOnInit(): void {
    this.http
      .get<{ status: string }>(this.config.tescoApiBaseUrl + '/health')
      .pipe(catchError(() => of(null)))
      .subscribe((h) => {
        this.healthOk.set(h?.status === 'ok');
      });

    // Use browse with limit=1 — just need the `total` count
    this.productsService.browse(0, 1).pipe(catchError(() => of(null))).subscribe((res) => {
      if (res?.total !== undefined) this.productCount.set(res.total);
    });

    // Load real statistics
    this.loadStatistics();

    // Load recent alerts for the dashboard panel (authenticated users only)
    if (this.auth.authenticated()) {
      this.alertsService.list()
        .pipe(catchError(() => of({ alerts: [] })))
        .subscribe(res => {
          const sorted = (res.alerts ?? []).sort(
            (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
          );
          const recent = sorted.slice(0, 4);
          this.recentAlerts.set(recent);
          this.alertsLoaded.set(true);

          // Resolve unique product names
          const ids = [...new Set(recent.map(a => a.productId))];
          if (ids.length === 0) return;
          const requests = ids.map(id =>
            this.productsService.get(id).pipe(catchError(() => of(null)))
          );
          forkJoin(requests).subscribe(products => {
            const names = new Map<string, string>();
            products.forEach((p, i) => {
              if (p?.name) names.set(ids[i], p.name);
            });
            this.alertProductNames.set(names);
          });
        });
    } else {
      this.alertsLoaded.set(true);
    }
  }

  private loadStatistics(): void {
    // Volatility - average of all tiers
    this.statsService
      .volatility()
      .pipe(catchError(() => of([])))
      .subscribe((tiers) => {
        if (tiers && tiers.length > 0) {
          const avgVol = tiers.reduce((sum, t) => sum + t.avg_volatility, 0) / tiers.length;
          if (avgVol < 0.005) {
            this.volatility.set('Very stable');
          } else if (avgVol < 0.01) {
            this.volatility.set('Stable');
          } else if (avgVol < 0.02) {
            this.volatility.set('Moderate');
          } else {
            this.volatility.set('Volatile');
          }
        }
      });

    // 30-day trend
    this.statsService
      .inflation30d()
      .pipe(catchError(() => of(null)))
      .subscribe((data) => {
        if (data && data.pct_change !== null) {
          const pct = data.pct_change;
          const icon = pct >= 0 ? '↑' : '↓';
          const sign = pct >= 0 ? '+' : '';
          this.trend30d.set(`${icon} ${sign}${pct.toFixed(1)}%`);
          // Buy signal based on trend
          if (pct < -2) {
            this.buySignal.set('✅ Below average');
          } else if (pct > 2) {
            this.buySignal.set('⚠️ Above average');
          } else {
            this.buySignal.set('➖ On average');
          }
        }
        this.statsLoading.set(false);
      });

    // Best weekday for shopping (highest discount %)
    this.statsService
      .discountByWeekday()
      .pipe(catchError(() => of([])))
      .subscribe((weekdays: DiscountByWeekday[]) => {
        if (weekdays && weekdays.length > 0) {
          const best = weekdays.reduce((prev, curr) =>
            (curr.avg_pct_off ?? 0) > (prev.avg_pct_off ?? 0) ? curr : prev
          );
          this.bestWeekday.set(best.weekday);
        }
      });

    // Max discount
    this.statsService
      .topDiscounts()
      .pipe(catchError(() => of([])))
      .subscribe((groups) => {
        if (groups && groups.length > 0) {
          const maxPct = groups[0].pct_off;
          this.maxDiscount.set(`${maxPct}%`);
        }
      });
  }

  timeOfDay(): string {
    const h = new Date().getHours();
    const key = h < 12 ? 'home.greeting.morning' : h < 18 ? 'home.greeting.afternoon' : 'home.greeting.evening';
    return this.tl.t(key);
  }

  readonly hexGrid = (() => {
    const colors = ['#00539F', '#3b9eff', '#F5A623', '#a855f7', '#008A00'];
    const rows: { s: number; op: number; color: string }[][] = [];
    for (let r = 0; r < 5; r++) {
      const row: { s: number; op: number; color: string }[] = [];
      for (let c = 0; c < 6; c++) {
        row.push({ s: 36, op: 0.08 + (r + c) * 0.025, color: colors[(r + c) % colors.length] });
      }
      rows.push(row);
    }
    return rows;
  })();

  readonly steps = [
    { n: 1, titleKey: 'home.step1.title', descKey: 'home.step1.desc' },
    { n: 2, titleKey: 'home.step2.title', descKey: 'home.step2.desc' },
    { n: 3, titleKey: 'home.step3.title', descKey: 'home.step3.desc' },
    { n: 4, titleKey: 'home.step4.title', descKey: 'home.step4.desc' },
  ];

  currentYear(): number {
    return new Date().getFullYear();
  }
}
