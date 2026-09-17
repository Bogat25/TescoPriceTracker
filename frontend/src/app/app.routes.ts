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
import { ComparePage } from './compare/compare-page';

export const routes: Routes = [
  {
    path: '',
    component: Home,
    title: 'Price Tracker — Prices, History and Alerts from Several Stores',
    data: {
      description: 'Compare grocery prices across Hungarian stores, follow price history and promotions, explore shopping analytics, and create free price-drop alerts.',
    },
  },
  {
    path: 'search',
    component: Search,
    title: 'Search Products — Price Tracker',
    data: {
      description: 'Search tracked products from several Hungarian stores and open detailed price histories, promotions and price analytics.',
    },
  },
  {
    path: 'products',
    component: ProductsList,
    title: 'Product Prices and History — Price Tracker',
    data: {
      description: 'Browse tracked products with each store\u2019s current price, discounts, categories and historical price data.',
    },
  },
  {
    path: 'products/:tpnc',
    component: ProductDetail,
    title: 'Product Price History — Price Tracker',
    data: {
      description: 'View this product\u2019s price in every store, its price history, promotions, trends and shopping analytics.',
    },
  },
  {
    path: 'p/:groupId',
    component: ComparePage,
    title: 'Price comparison',
    data: {
      description: 'Compare the current price, promotions, card prices and price history of this product across stores.',
    },
  },
  {
    path: 'o/:ref',
    component: ComparePage,
    title: 'Product price history',
    data: {
      description: 'Current price, promotions and price history of this product.',
    },
  },
  {
    path: 'alerts',
    component: Alerts,
    canActivate: [authGuard],
    title: 'My Price Alerts — Price Tracker',
    data: { robots: 'noindex, nofollow' },
  },
  {
    path: 'statistics',
    component: Statistics,
    title: 'Price Statistics and Trends — Price Tracker',
    data: {
      description: 'Explore price trends, inflation, discounts, volatility and historical shopping statistics across stores.',
    },
  },
  {
    path: 'user-settings',
    component: UserSettings,
    canActivate: [authGuard],
    title: 'Account Settings — Price Tracker',
    data: { robots: 'noindex, nofollow' },
  },
  {
    path: 'privacy',
    component: PrivacyPolicy,
    title: 'Privacy Policy — Price Tracker',
    data: {
      description: 'Read how Price Tracker handles account, usage, price-alert and browser extension data.',
    },
  },
  { path: '**', redirectTo: '' },
];
