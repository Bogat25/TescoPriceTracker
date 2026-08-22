import { Routes } from '@angular/router';
import { Home } from './home/home';
import { Search } from './search/search';
import { ProductDetail } from './product-detail/product-detail';
import { ProductsList } from './products-list/products-list';
import { Alerts } from './alerts/alerts';
import { UserSettings } from './user-settings/user-settings';
import { Statistics } from './statistics/statistics';
import { PrivacyPolicy } from './privacy-policy/privacy-policy';
import { authGuard } from './auth/auth.guard';

export const routes: Routes = [
  {
    path: '',
    component: Home,
    title: 'Tesco Price Tracker — Price History, Analytics and Alerts',
    data: {
      description: 'Track Tesco Hungary product prices, compare price history and promotions, explore shopping analytics, and create free price-drop alerts.',
    },
  },
  {
    path: 'search',
    component: Search,
    title: 'Search Tesco Products — Tesco Price Tracker',
    data: {
      description: 'Search tracked Tesco Hungary products and open detailed price histories, promotions and price analytics.',
    },
  },
  {
    path: 'products',
    component: ProductsList,
    title: 'Tesco Product Prices and History — Tesco Price Tracker',
    data: {
      description: 'Browse tracked Tesco Hungary products with current prices, discounts, categories, ratings and historical price data.',
    },
  },
  {
    path: 'products/:tpnc',
    component: ProductDetail,
    title: 'Tesco Product Price History — Tesco Price Tracker',
    data: {
      description: 'View this Tesco product’s current price, price history, promotions, trends and shopping analytics.',
    },
  },
  {
    path: 'alerts',
    component: Alerts,
    canActivate: [authGuard],
    title: 'My Price Alerts — Tesco Price Tracker',
    data: { robots: 'noindex, nofollow' },
  },
  {
    path: 'statistics',
    component: Statistics,
    title: 'Tesco Price Statistics and Trends — Tesco Price Tracker',
    data: {
      description: 'Explore Tesco Hungary price trends, inflation, discounts, volatility and historical shopping statistics.',
    },
  },
  {
    path: 'user-settings',
    component: UserSettings,
    canActivate: [authGuard],
    title: 'Account Settings — Tesco Price Tracker',
    data: { robots: 'noindex, nofollow' },
  },
  {
    path: 'privacy',
    component: PrivacyPolicy,
    title: 'Privacy Policy — Tesco Price Tracker',
    data: {
      description: 'Read how Tesco Price Tracker handles account, usage, price-alert and browser extension data.',
    },
  },
  { path: '**', redirectTo: '' },
];
