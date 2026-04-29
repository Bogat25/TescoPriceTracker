import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { catchError, of } from 'rxjs';
import { AppConfigService } from '../services/app-config.service';

@Component({
  selector: 'app-home',
  imports: [CommonModule, RouterLink],
  templateUrl: './home.html',
  styleUrl: './home.scss',
})
export class Home implements OnInit {
  private http = inject(HttpClient);
  private config = inject(AppConfigService);

  readonly healthOk = signal<boolean | null>(null);
  readonly productCount = signal<number | null>(null);
  readonly statsLoading = signal(true);

  ngOnInit(): void {
    const base = this.config.tescoApiBaseUrl;

    this.http
      .get<{ status: string; upstream: string }>(`${base}/health`)
      .pipe(catchError(() => of(null)))
      .subscribe((h) => {
        this.healthOk.set(h?.status === 'ok' && h?.upstream === 'ok');
      });

    this.http
      .get<unknown>(`${base}/products`)
      .pipe(catchError(() => of(null)))
      .subscribe((res) => {
        this.statsLoading.set(false);
        if (Array.isArray(res)) {
          this.productCount.set(res.length);
        } else if (res && typeof res === 'object') {
          const r = res as Record<string, unknown>;
          const count = r['count'] ?? r['total'] ?? r['length'];
          if (typeof count === 'number') this.productCount.set(count);
        }
      });
  }
}
