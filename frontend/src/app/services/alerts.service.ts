import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export type AlertDirection = 'below' | 'above';

export interface PriceAlert {
  id: number;
  userId: string;
  tpnc: string;
  threshold: number;
  direction: AlertDirection;
  createdAt: string;
}

export interface CreateAlertRequest {
  tpnc: string;
  threshold: number;
  direction: AlertDirection;
}

@Injectable({ providedIn: 'root' })
export class AlertsService {
  private http = inject(HttpClient);
  private readonly base = '/api/tesco/alerts';

  list(): Observable<{ alerts: PriceAlert[] }> {
    return this.http.get<{ alerts: PriceAlert[] }>(this.base);
  }

  create(req: CreateAlertRequest): Observable<PriceAlert> {
    return this.http.post<PriceAlert>(this.base, req);
  }

  remove(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }
}
