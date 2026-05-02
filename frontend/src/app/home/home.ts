import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { catchError, of } from 'rxjs';
import { AppConfigService } from '../services/app-config.service';
import { PlatformStatsService, DiscountByWeekday } from '../services/platform-stats.service';
import { AuthService } from '../services/auth.service';
import { HexKpi }   from '../shared/hex-kpi/hex-kpi';
import { HexIcon }  from '../shared/hex-icon/hex-icon';
import { SecLabel } from '../shared/sec-label/sec-label';

@Component({
  selector: 'app-home',
  imports: [CommonModule, RouterLink, HexKpi, SecLabel],
  templateUrl: './home.html',
  styleUrl: './home.scss',
})
export class Home implements OnInit {
  private http = inject(HttpClient);
  private config = inject(AppConfigService);
  private statsService = inject(PlatformStatsService);
  readonly auth = inject(AuthService);

  readonly healthOk = signal<boolean | null>(null);
  readonly productCount = signal<number | null>(null);
  readonly statsLoading = signal(true);

  readonly volatility = signal<string>('');
  readonly trend30d = signal<string>('');
  readonly bestWeekday = signal<string>('');
  readonly maxDiscount = signal<string>('');
  readonly buySignal = signal<string>('');

  ngOnInit(): void {
    this.http
      .get<{ status: string }>('/health')
      .pipe(catchError(() => of(null)))
      .subscribe((h) => {
        this.healthOk.set(h?.status === 'ok');
      });

    this.http
      .get<unknown>('/api/v1/products')
      .pipe(catchError(() => of(null)))
      .subscribe((res) => {
        if (Array.isArray(res)) {
          this.productCount.set(res.length);
        } else if (res && typeof res === 'object') {
          const r = res as Record<string, unknown>;
          const count = r['count'] ?? r['total'] ?? r['length'];
          if (typeof count === 'number') this.productCount.set(count);
        }
      });

    // Load real statistics
    this.loadStatistics();
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
    if (h < 12) return 'morning';
    if (h < 18) return 'afternoon';
    return 'evening';
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
    { n: 1, title: 'Search',  desc: 'Find a product by name or TPNC code.' },
    { n: 2, title: 'Explore', desc: 'View full price history across all channels.' },
    { n: 3, title: 'Analyse', desc: 'Open statistics for deep analytics and insights.' },
    { n: 4, title: 'Alert',   desc: 'Set a target price and buy at the right moment.' },
  ];
}
