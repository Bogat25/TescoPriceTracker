import { TestBed } from '@angular/core/testing';
import { Subject, of } from 'rxjs';

import { Alerts } from './alerts';
import { AlertsService } from '../services/alerts.service';
import { AuthService, GatewayUser } from '../services/auth.service';
import { AlertProductsService } from '../services/alert-products.service';
import { StoresService } from '../services/stores.service';
import { TranslationService } from '../services/translation.service';

describe('Alerts authentication bootstrap', () => {
  it('waits for the in-flight session lookup before deciding the user is anonymous', () => {
    const session = new Subject<GatewayUser | null>();
    let listCalls = 0;
    const auth = {
      authenticated: () => false,
      checkSession: () => session.asObservable(),
    };
    const alertsApi = {
      list: () => {
        listCalls += 1;
        return of({ alerts: [] });
      },
      getEmailPreference: () => of({ emailEnabled: true }),
    };

    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: auth },
        { provide: AlertsService, useValue: alertsApi },
        { provide: AlertProductsService, useValue: { resolve: () => of(new Map()) } },
        { provide: StoresService, useValue: { load: () => of([]), name: (id: string) => id } },
        { provide: TranslationService, useValue: {} },
      ],
    });

    const component = TestBed.runInInjectionContext(() => new Alerts());
    component.ngOnInit();

    expect(component.loading()).toBe(true);
    expect(component.error()).toBe('');
    expect(listCalls).toBe(0);

    session.next({ name: 'Tester', sub: '123', claims: [] });

    expect(component.loading()).toBe(false);
    expect(component.error()).toBe('');
    expect(listCalls).toBe(1);
  });
});
