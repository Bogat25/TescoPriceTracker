import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export type AlertType = 'TARGET_PRICE' | 'PERCENTAGE_DROP';

export interface PriceAlert {
  id: string;
  userId: string;
  /** Tesco alerts keep the bare tpnc here (the browser extension matches on it). */
  productId: string;
  /** What is watched: an offer (``auchan:678170``) or a product in every store (``g:5998…``). */
  target: string;
  /** Stores the alert watches. */
  stores: string[];
  /** True while none of the watched stores is available. */
  paused?: boolean;
  alertType: AlertType;
  targetPrice: number | null;
  dropPercentage: number | null;
  basePriceAtCreation: number | null;
  enabled: boolean;
  createdAt: string;
}

/** ``target`` is an offer ref or a group ID; ``stores`` narrows a group alert (omitted = every store). */
export type AlertTarget = { productId: string } | { target: string; stores?: string[] };

export type CreateAlertRequest = AlertTarget &
  (
    | { alertType: 'TARGET_PRICE'; targetPrice: number }
    | { alertType: 'PERCENTAGE_DROP'; dropPercentage: number; basePriceAtCreation: number }
  );

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
