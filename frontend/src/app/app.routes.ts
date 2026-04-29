import { Routes } from '@angular/router';
import { Home } from './home/home';
import { Search } from './search/search';
import { ProductDetail } from './product-detail/product-detail';
import { Alerts } from './alerts/alerts';
import { UserSettings } from './user-settings/user-settings';
import { Statistics } from './statistics/statistics';
import { authGuard } from './auth/auth.guard';

export const routes: Routes = [
  { path: '', component: Home, title: 'Tesco Price Tracker' },
  { path: 'search', component: Search, title: 'Search — Tesco Price Tracker' },
  { path: 'products/:tpnc', component: ProductDetail, title: 'Product — Tesco Price Tracker' },
  { path: 'alerts', component: Alerts, canActivate: [authGuard], title: 'My Alerts' },
  { path: 'statistics', component: Statistics, title: 'Statistics — Tesco Price Tracker' },
  { path: 'user-settings', component: UserSettings, canActivate: [authGuard], title: 'Account Settings' },
  { path: '**', redirectTo: '' },
];
