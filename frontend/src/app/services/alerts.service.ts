import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export type AlertType = 'TARGET_PRICE' | 'PERCENTAGE_DROP';

export interface PriceAlert {
  id: string;
  userId: string;
  productId: string;
  alertType: AlertType;
  targetPrice: number | null;
  dropPercentage: number | null;
  basePriceAtCreation: number | null;
  enabled: boolean;
  createdAt: string;
}

export type CreateAlertRequest =
  | { productId: string; alertType: 'TARGET_PRICE'; targetPrice: number }
  | { productId: string; alertType: 'PERCENTAGE_DROP'; dropPercentage: number; basePriceAtCreation: number };

@Injectable({ providedIn: 'root' })
export class AlertsService {
  private http = inject(HttpClient);
  private readonly base = '/api/alerts';

  list(): Observable<{ alerts: PriceAlert[] }> {
    return this.http.get<{ alerts: PriceAlert[] }>(`${this.base}/`);
  }

  create(req: CreateAlertRequest): Observable<PriceAlert> {
    return this.http.post<PriceAlert>(`${this.base}/`, req);
  }

  toggle(id: string, enabled: boolean): Observable<PriceAlert> {
    return this.http.patch<PriceAlert>(`${this.base}/${id}/toggle`, { enabled });
  }

  remove(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }

  getEmailPreference(): Observable<{ emailEnabled: boolean }> {
    return this.http.get<{ emailEnabled: boolean }>(`${this.base}/prefs`);
  }

  setEmailPreference(emailEnabled: boolean): Observable<{ emailEnabled: boolean }> {
    return this.http.patch<{ emailEnabled: boolean }>(`${this.base}/prefs`, { emailEnabled });
  }
}
